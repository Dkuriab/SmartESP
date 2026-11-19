import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SideList from './SideList'

function setup(over: Partial<CoreState> = {}) {
  const actions = makeActions()
  render(<SideList state={makeState({ config: makeConfig(), ...over })} actions={actions} />)
  return { actions }
}

const section = (name: string) => screen.getByRole('region', { name })

describe('SideList', () => {
  it('колонки с точкой «в сети», клик выбирает колонку', async () => {
    const { actions } = setup()
    const devices = section('Колонки 2')
    expect(within(devices).getByLabelText('в сети')).toBeInTheDocument()
    expect(within(devices).getByLabelText('не в сети')).toBeInTheDocument()
    await userEvent.click(within(devices).getByRole('button', { name: /Спальня/ }))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'device', id: 'b' })
  })

  it('колонка без имени подписана MAC; ноль колонок — подсказка', () => {
    setup({ status: makeStatus({ devices: [{ device_id: 'aa:bb', name: '', connected: true, remote: '', fw: '' }] }) })
    expect(screen.getByRole('button', { name: /aa:bb/ })).toBeInTheDocument()
  })

  it('ноль колонок — «Колонок пока нет»', () => {
    setup({ status: makeStatus({ devices: [] }) })
    expect(screen.getByText('Колонок пока нет')).toBeInTheDocument()
  })

  it('обработчики: переключатель шлёт список без обработчика, клик по имени выбирает', async () => {
    const { actions } = setup()
    const stages = section('Обработчики')
    await userEvent.click(within(stages).getByRole('switch', { name: 'Шёпот' }))
    expect(actions.setStages).toHaveBeenCalledWith([])
    expect(actions.select).not.toHaveBeenCalled()
    await userEvent.click(within(stages).getByRole('button', { name: /Шёпот/ }))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'stage', id: 'whisper_detect' })
  })

  it('диспетчер и голос показывают модель и голос, выбираются кликом', async () => {
    const { actions } = setup({ selected: { kind: 'voice', id: 'voice' } })
    const dispatcher = screen.getByRole('button', { name: /Диспетчер/ })
    expect(dispatcher).toHaveTextContent('qwen3')
    const voice = screen.getByRole('button', { name: /Голос/ })
    expect(voice).toHaveTextContent('piper · irina')
    expect(voice).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(dispatcher)
    expect(actions.select).toHaveBeenCalledWith({ kind: 'dispatcher', id: 'dispatcher' })
  })

  it('внизу — «Доступ из сети»', async () => {
    setup()
    expect(await screen.findByText('Адрес в сети не найден')).toBeInTheDocument()
  })
})
