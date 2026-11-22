import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreEvent } from '../../api/events'
import type { Device } from '../../state/model'
import { reduce } from '../../state/reducer'
import { makeState, makeStatus } from '../fixtures'
import DeviceUpdate, { describeUpdate } from './DeviceUpdate'

const device = (over: Partial<Device> = {}): Device => ({
  device_id: 'a',
  name: 'Кухня',
  connected: true,
  remote: '',
  fw: '0.5.0',
  protocol: 4,
  ...over,
})

describe('DeviceUpdate', () => {
  it('старая прошивка — подсказка про USB; новая — выбор файла уходит в onInstall', async () => {
    const { rerender } = render(<DeviceUpdate device={device({ protocol: 3 })} onInstall={vi.fn()} />)
    expect(screen.getByText(/первый раз прошейте её по USB/)).toBeInTheDocument()
    const onInstall = vi.fn()
    rerender(<DeviceUpdate device={device()} onInstall={onInstall} />)
    const file = new File([new Uint8Array([0xe9])], 'SmartEsp.ino.bin')
    await userEvent.upload(screen.getByLabelText('Файл прошивки'), file)
    expect(onInstall).toHaveBeenCalledWith(file)
  })

  it('ход обновления: полоса и проценты, во время — кнопка недоступна; ошибка — по-русски', () => {
    const update = { what: 'firmware', state: 'progress', done: 1024 * 1024, total: 2 * 1024 * 1024, error: '', at: 1 }
    render(<DeviceUpdate device={device({ update })} onInstall={vi.fn()} />)
    expect(screen.getByRole('status')).toHaveTextContent('Прошивка: скачано 1024 КБ из 2048 КБ (50 %)')
    expect(screen.getByRole('button', { name: 'Обновить прошивку…' })).toBeDisabled()
    const failed = describeUpdate({ ...update, what: 'model', state: 'failed', error: 'hash' })
    expect(failed).toEqual({ text: 'Модель слова: не удалось — файл повредился по дороге', share: null, bad: true })
  })

  it('событие device_update сразу меняет колонку в status', () => {
    const state = makeState({ status: makeStatus({ devices: [device()] }) })
    const data = { device_id: 'a', what: 'model', state: 'done', done: 10, total: 10, error: '', at: 5 }
    const next = reduce(state, { type: 'event', event: { kind: 'device_update', data, at: 5 } as CoreEvent })
    expect(next.status?.devices[0]?.update).toEqual({ what: 'model', state: 'done', done: 10, total: 10, error: '', at: 5 })
  })
})
