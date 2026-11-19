import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LogHandlers } from '../../api/logs'
import { FLUSH_MS } from '../../state/logs'
import { makeActions, makeState, makeStatus } from '../fixtures'
import CoreTab from './CoreTab'
import { formatUptime } from './uptime'

const info = { version: '0.3.0', uptime_s: 10, state: 'ready' as const, port: 8765, data_dir: '/Users/a/SmartEsp' }

afterEach(() => {
  delete (window as { smartespBridge?: unknown }).smartespBridge
  delete (window as { webkit?: unknown }).webkit
})

function withLogs() {
  const actions = makeActions()
  let handlers: LogHandlers | undefined
  vi.mocked(actions.watchLogs).mockImplementation((h) => {
    handlers = h
    return () => {}
  })
  return { actions, send: () => handlers }
}

describe('вкладка «Ядро»', () => {
  it('время работы по-русски', () => {
    expect([40, 720, 3 * 3600 + 5 * 60, 2 * 86400 + 3600].map(formatUptime)).toEqual(['40 с', '12 мин', '3 ч 05 мин', '2 д 1 ч'])
  })

  it('показывает версию, время работы, порт и папку данных', async () => {
    const actions = makeActions()
    vi.mocked(actions.loadCoreInfo).mockResolvedValue(info)
    render(<CoreTab state={makeState({ status: makeStatus({ version: '0.3.0', uptime_s: 125 }) })} actions={actions} />)
    expect(await screen.findByText('/Users/a/SmartEsp')).toBeInTheDocument()
    expect(screen.getByText('8765')).toBeInTheDocument()
    expect(screen.getByText('0.3.0')).toBeInTheDocument()
    expect(screen.getByText('2 мин')).toBeInTheDocument()
  })

  it('«Остановить» спрашивает на месте; «Отмена» ничего не шлёт', async () => {
    const actions = makeActions()
    render(<CoreTab state={makeState()} actions={actions} />)
    await userEvent.click(screen.getByRole('button', { name: 'Остановить' }))
    await userEvent.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(actions.stopCore).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Остановить' }))
    await userEvent.click(screen.getByRole('button', { name: 'Да, остановить' }))
    expect(actions.stopCore).toHaveBeenCalledTimes(1)
    expect(await screen.findByText(/Ядро останавливается/)).toBeInTheDocument()
  })

  it('«Перезапустить» вызывает restart; без связи кнопки неактивны', async () => {
    const actions = makeActions()
    const { rerender } = render(<CoreTab state={makeState()} actions={actions} />)
    await userEvent.click(screen.getByRole('button', { name: 'Перезапустить' }))
    expect(actions.restart).toHaveBeenCalled()
    rerender(<CoreTab state={makeState({ connection: 'offline' })} actions={actions} />)
    expect(screen.getByRole('button', { name: 'Перезапустить' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Остановить' })).toBeDisabled()
  })

  it('модели в памяти: «Выгрузить» зовёт unloadModel с именем', async () => {
    const actions = makeActions()
    const status = makeStatus({ ollama: { reachable: true, loaded: ['qwen3:8b', 'gemma3'] } })
    const { rerender } = render(<CoreTab state={makeState({ status })} actions={actions} />)
    await userEvent.click(screen.getAllByRole('button', { name: 'Выгрузить' })[1]!)
    expect(actions.unloadModel).toHaveBeenCalledWith('gemma3')
    rerender(<CoreTab state={makeState({ status: makeStatus({ ollama: { reachable: false, loaded: [] } }) })} actions={actions} />)
    expect(screen.getByText('Ollama недоступна')).toBeInTheDocument()
  })

  it('кнопки приложения видны только при мосте и шлют действие', async () => {
    const actions = makeActions()
    const { unmount } = render(<CoreTab state={makeState()} actions={actions} />)
    expect(screen.queryByRole('button', { name: 'Папка данных' })).not.toBeInTheDocument()
    unmount()
    Object.assign(window, { smartespBridge: true, webkit: { messageHandlers: { smartesp: { postMessage: vi.fn() } } } })
    render(<CoreTab state={makeState()} actions={actions} />)
    for (const name of ['Папка данных', 'config.yaml']) expect(screen.getByRole('button', { name })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Журнал в Finder' }))
    expect(actions.openInApp).toHaveBeenCalledWith('revealLog')
  })

  it('журнал: строки, фильтр «Ошибки», пауза прокрутки и возврат к последним', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const { actions, send } = withLogs()
    render(<CoreTab state={makeState()} actions={actions} />)
    act(() => {
      send()?.onOpen()
      send()?.onLine({ at: 1, level: 'INFO', text: 'Ядро готово' })
      send()?.onLine({ at: 2, level: 'ERROR', text: 'Ollama упала' })
      vi.advanceTimersByTime(FLUSH_MS)
    })
    vi.useRealTimers()
    expect(screen.getByText('Ядро готово')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ошибки' }))
    expect(screen.queryByText('Ядро готово')).not.toBeInTheDocument()
    expect(screen.getByText('Ollama упала')).toHaveClass('level-error')
    const box = screen.getByTestId('log-lines')
    Object.defineProperty(box, 'scrollHeight', { value: 1000, configurable: true })
    Object.defineProperty(box, 'clientHeight', { value: 200, configurable: true })
    box.scrollTop = 100
    act(() => box.dispatchEvent(new Event('scroll')))
    await userEvent.click(screen.getByRole('button', { name: 'К последним строкам' }))
    expect(box.scrollTop).toBe(1000)
    expect(screen.queryByRole('button', { name: 'К последним строкам' })).not.toBeInTheDocument()
  })
})
