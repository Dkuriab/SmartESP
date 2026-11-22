import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreEvent } from '../../api/events'
import type { Echo } from '../../state/echo'
import { applyEchoEvent } from '../../state/echo'
import type { Device } from '../../state/model'
import { makeActions, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const echo: Echo = { state: 'current', delay_ms: 20, previous_ms: 20, confidence: 0, error: '', at: 1 }
const v7: Device = { device_id: 'aa:bb', name: 'Кухня', connected: true, remote: '', fw: '0.7.0', protocol: 5, volume: 50, echo }

function setup(device: Device) {
  const actions = makeActions()
  const state = makeState({ status: makeStatus({ devices: [device] }), selected: { kind: 'device', id: 'aa:bb' } })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

const status = () => screen.getByRole('status', { name: 'Эхо' })
const button = () => screen.getByRole('button', { name: 'Калибровка эха' })

describe('калибровка эха в панели колонки', () => {
  it('сдвиг сейчас и кнопка калибровки; проверки после неё описаны', async () => {
    const { actions } = setup(v7)
    expect(status()).toHaveTextContent('Сдвиг образца: 20 мс')
    expect(screen.getByText(/громкая музыка на колонке/)).toBeInTheDocument()
    await userEvent.click(button())
    expect(actions.calibrateEcho).toHaveBeenCalledWith('aa:bb')
  })

  it('идёт — кнопка заблокирована; готово — новый сдвиг и уверенность', () => {
    setup({ ...v7, echo: { ...echo, state: 'running' } })
    expect(button()).toBeDisabled()
  })

  it('итог и ошибка понятны', () => {
    setup({ ...v7, echo: { ...echo, state: 'done', delay_ms: 27, confidence: 0.71 } })
    expect(status()).toHaveTextContent('Готово: сдвиг 27 мс (был 20), уверенность 71%')
  })

  it('не вышло — причина и прежний сдвиг', () => {
    setup({ ...v7, echo: { ...echo, state: 'failed', error: 'weak' } })
    expect(status()).toHaveTextContent('Не вышло: микрофон не услышал шум уверенно')
  })

  it('старая прошивка — блока нет', () => {
    setup({ ...v7, echo: null })
    expect(screen.queryByRole('button', { name: 'Калибровка эха' })).toBeNull()
  })

  it('событие device_echo обновляет колонку; мусор — мимо', () => {
    const state = makeState({ status: makeStatus({ devices: [v7] }) })
    const event = (data: Record<string, unknown>): CoreEvent => ({ kind: 'device_echo', data, at: 0 })
    const next = applyEchoEvent(state, event({ device_id: 'aa:bb', ...echo, state: 'done', delay_ms: 31 }))
    expect(next.status?.devices[0]?.echo?.delay_ms).toBe(31)
    expect(applyEchoEvent(state, event({ device_id: 'aa:bb', state: 'odd' }))).toBe(state)
  })
})
