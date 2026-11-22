import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState, Stream } from '../../state/model'
import { makeActions, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const v5 = { device_id: 'aa:bb', name: 'Кухня', connected: true, remote: '', fw: '0.6.0', protocol: 5 }
const playing: Stream = {
  device_id: 'aa:bb',
  name: 'Кухня',
  available: true,
  state: 'playing',
  title: 'Группа крови',
  index: 1,
  count: 3,
  position_s: 3,
  live: false,
  volume: 0.6,
  error: '',
}

function setup(device = v5, over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({ status: makeStatus({ devices: [device] }), selected: { kind: 'device', id: 'aa:bb' }, ...over })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

const music = () => screen.getByRole('status', { name: 'Музыка' })

describe('музыка на колонке в панели', () => {
  it('играет — название, место в очереди и кнопки', async () => {
    const { actions } = setup(v5, { streams: { 'aa:bb': playing } })
    expect(music()).toHaveTextContent('Играет «Группа крови» (2 из 3)')
    await userEvent.click(screen.getByRole('button', { name: 'Пауза' }))
    expect(actions.controlStream).toHaveBeenCalledWith('aa:bb', 'pause')
    await userEvent.click(screen.getByRole('button', { name: 'Дальше' }))
    await userEvent.click(screen.getByRole('button', { name: 'Стоп' }))
    expect(actions.controlStream).toHaveBeenLastCalledWith('aa:bb', 'stop')
  })

  it('на паузе — «Продолжить»; одна станция — без «Дальше»', async () => {
    const { actions } = setup(v5, { streams: { 'aa:bb': { ...playing, state: 'paused', count: 1, title: 'Радио' } } })
    expect(music()).toHaveTextContent('Пауза: «Радио»')
    expect(screen.queryByRole('button', { name: 'Дальше' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Продолжить' }))
    expect(actions.controlStream).toHaveBeenCalledWith('aa:bb', 'resume')
  })

  it('не играет — ошибка или «Не играет», без кнопок', () => {
    setup(v5, { streams: { 'aa:bb': { ...playing, state: 'idle', error: 'Колонка не начала играть' } } })
    expect(music()).toHaveTextContent('Колонка не начала играть')
    expect(screen.queryByRole('button', { name: 'Стоп' })).toBeNull()
  })

  it('старая прошивка — подсказка', () => {
    setup({ ...v5, protocol: 4 })
    expect(screen.getByText('Музыку играют колонки с прошивкой 0.6.0')).toBeInTheDocument()
  })
})
