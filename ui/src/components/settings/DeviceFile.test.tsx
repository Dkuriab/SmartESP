import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const v3 = { device_id: 'aa:bb', name: 'Кухня', connected: true, remote: '', fw: '2.0', protocol: 3 }

function setup(device = v3, over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({ status: makeStatus({ devices: [device] }), selected: { kind: 'device', id: 'aa:bb' }, ...over })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

const play = () => screen.getByRole('button', { name: 'Проиграть файл…' })
const stop = () => screen.getByRole('button', { name: 'Остановить' })

describe('файл на колонке в панели', () => {
  it('выбранный файл уходит в playFile', async () => {
    const { actions } = setup()
    expect(play()).toBeEnabled()
    const file = new File(['ID3'], 'song.mp3', { type: 'audio/mpeg' })
    await userEvent.upload(screen.getByLabelText('Звуковой файл'), file)
    expect(actions.playFile).toHaveBeenCalledWith('aa:bb', file)
    expect(screen.getByLabelText('Звуковой файл')).toHaveAttribute('accept', 'audio/*,.mp3,.wav,.ogg,.oga,.opus,.m4a')
  })

  it('«Остановить» вызывает stopFile', async () => {
    const { actions } = setup(v3, { files: { 'aa:bb': 'playing' } })
    expect(screen.getByRole('status')).toHaveTextContent('Играет')
    expect(play()).toBeDisabled()
    await userEvent.click(stop())
    expect(actions.stopFile).toHaveBeenCalledWith('aa:bb')
  })

  it('пока загружается — обе кнопки заблокированы', () => {
    setup(v3, { files: { 'aa:bb': 'sending' } })
    expect(screen.getByRole('status')).toHaveTextContent('Загружается…')
    expect(play()).toBeDisabled()
    expect(stop()).toBeDisabled()
  })

  it.each([
    [{ ...v3, protocol: 2 }, 'Файлы играют колонки с новой прошивкой'],
    [{ ...v3, connected: false }, 'Колонка не в сети'],
  ])('колонка без поддержки — кнопки заблокированы с подсказкой', (device, hint) => {
    setup(device)
    expect(play()).toBeDisabled()
    expect(stop()).toBeDisabled()
    expect(screen.getByText(hint)).toBeInTheDocument()
  })
})
