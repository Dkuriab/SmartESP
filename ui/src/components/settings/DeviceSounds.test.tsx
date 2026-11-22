import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreEvent } from '../../api/events'
import type { Device } from '../../state/model'
import { reduce } from '../../state/reducer'
import type { DeviceSound, SoundActions, SoundsOverview } from '../../state/soundActions'
import { makeActions, makeState } from '../fixtures'
import DeviceSounds from './DeviceSounds'
import { deliveryText, soundText } from './sounds'

const device: Device = { device_id: 'a', name: 'Кухня', connected: false, remote: '', fw: '0.6.0', protocol: 5, volume: 0.5 }
const bell = { sha256: 'f'.repeat(64), name: 'bell.mp3', duration_s: 1.2 }

function tone(over: Partial<DeviceSound> & Pick<DeviceSound, 'tone'>): DeviceSound {
  return { sound: null, delivery: 'ok', error: '', ...over }
}

function overview(supported: boolean | null = true, others = true): SoundsOverview {
  const tones: DeviceSound[] = [
    tone({ tone: 'wake', sound: bell, delivery: 'offline' }),
    tone({ tone: 'error', delivery: 'failed', error: 'нет места во флеше колонки' }),
    tone({ tone: 'thinking' }),
    tone({ tone: 'listen' }),
    tone({ tone: 'attention' }),
  ]
  const devices = [{ device_id: 'a', supported, tones }]
  if (others) devices.push({ device_id: 'b', supported: null, tones })
  return { devices }
}

function actionsWith(data: SoundsOverview): SoundActions {
  const actions = makeActions()
  vi.mocked(actions.loadSounds).mockResolvedValue(data)
  return actions
}

describe('DeviceSounds', () => {
  it('сигналы этой колонки: звук и доставка; замена, встроенный, повтор и копия — для неё', async () => {
    const actions = actionsWith(overview())
    render(<DeviceSounds device={device} tick={0} actions={actions} />)
    expect(await screen.findByText('bell.mp3 · 1.2 с')).toBeInTheDocument()
    expect(screen.getByLabelText('Доставка: Слово услышано')).toHaveTextContent('ждёт подключения колонки')
    expect(screen.getByLabelText('Доставка: Ошибка')).toHaveTextContent('ошибка: нет места во флеше колонки · Повторить')
    const file = new File([new Uint8Array([1, 2])], 'ding.wav')
    await userEvent.upload(screen.getByLabelText('Файл звука: Думаю'), file)
    expect(actions.uploadSound).toHaveBeenCalledWith('thinking', file, 'a')
    const resets = screen.getAllByRole('button', { name: 'Встроенный' })
    expect(resets[1]).toBeDisabled() // «Слушаю» — уже встроенный
    await userEvent.click(resets[0]!) // «Слово услышано»
    expect(actions.resetSound).toHaveBeenCalledWith('wake', 'a')
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }))
    expect(actions.resyncSounds).toHaveBeenCalledWith('a')
    await userEvent.click(screen.getByRole('button', { name: 'Скопировать на другие колонки' }))
    expect(actions.copySounds).toHaveBeenCalledWith('a')
  })

  it('свой звук слушается через ядро; старая прошивка — подсказка; одна колонка — копировать некуда', async () => {
    const actions = actionsWith(overview(false, false))
    render(<DeviceSounds device={device} tick={0} actions={actions} />)
    expect(await screen.findByText(/с прошивки 0.6.0/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Скопировать на другие колонки' })).toBeDisabled()
    await userEvent.click(screen.getByLabelText('Прослушать: Слово услышано'))
    expect(actions.fetchSound).toHaveBeenCalledWith(bell.sha256)
  })

  it('подписи и событие sounds', () => {
    expect(soundText(tone({ tone: 'wake' }))).toBe('встроенный')
    expect(deliveryText(tone({ tone: 'wake', delivery: 'sending' }))).toBe('доставляется')
    expect(deliveryText(tone({ tone: 'wake' }))).toBe('на колонке')
    const state = makeState()
    const next = reduce(state, { type: 'event', event: { kind: 'sounds', data: { device_id: 'a' }, at: 1 } as CoreEvent })
    expect(next.soundsTick).toBe(state.soundsTick + 1)
  })
})
