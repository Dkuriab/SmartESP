import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreEvent } from '../../api/events'
import type { Device } from '../../state/model'
import { reduce } from '../../state/reducer'
import type { DeviceSound, SoundActions, SoundsOverview } from '../../state/soundActions'
import { makeActions, makeState } from '../fixtures'
import DeviceSounds from './DeviceSounds'
import { deliveryText, sourceText } from './sounds'

const device: Device = { device_id: 'a', name: 'Кухня', connected: true, remote: '', fw: '0.6.0', protocol: 4, volume: 50 }
const bell = { sha256: 'f'.repeat(64), name: 'bell.mp3', duration_s: 1.2 }

function tone(over: Partial<DeviceSound> & Pick<DeviceSound, 'tone'>): DeviceSound {
  return { source: 'builtin', sound: null, delivery: 'ok', error: '', ...over }
}

function overview(supported: boolean | null = true): SoundsOverview {
  const tones: DeviceSound[] = [
    tone({ tone: 'wake', source: 'all', sound: bell }),
    tone({ tone: 'error', delivery: 'failed', error: 'нет места во флеше колонки' }),
    tone({ tone: 'thinking' }),
    tone({ tone: 'listen' }),
    tone({ tone: 'attention' }),
  ]
  const common = [{ tone: 'wake' as const, sound: bell }]
  return { common, devices: [{ device_id: 'a', supported, tones }] }
}

function actionsWith(data: SoundsOverview): SoundActions {
  const actions = makeActions()
  vi.mocked(actions.loadSounds).mockResolvedValue(data)
  return actions
}

describe('DeviceSounds', () => {
  it('сигналы с источником и доставкой; «Заменить…» для всех колонок, «Встроенный» — для этой', async () => {
    const actions = actionsWith(overview())
    render(<DeviceSounds device={device} tick={0} actions={actions} />)
    expect(await screen.findByText('общий: bell.mp3 · 1.2 с')).toBeInTheDocument()
    expect(screen.getByText('не доставлен: нет места во флеше колонки')).toBeInTheDocument()
    const file = new File([new Uint8Array([1, 2])], 'ding.wav')
    await userEvent.upload(screen.getByLabelText('Файл звука: Думаю'), file)
    expect(actions.uploadSound).toHaveBeenCalledWith('thinking', file, null)
    await userEvent.click(screen.getByLabelText(/Для всех колонок/))
    const resets = screen.getAllByRole('button', { name: 'Встроенный' })
    await userEvent.click(resets[0]!) // первый — «Слово услышано»
    expect(actions.resetSound).toHaveBeenCalledWith('wake', 'a')
    await userEvent.click(screen.getByRole('button', { name: 'Повторить доставку' }))
    expect(actions.resyncSounds).toHaveBeenCalled()
  })

  it('свой звук слушается через ядро; старая прошивка — подсказка', async () => {
    const actions = actionsWith(overview(false))
    render(<DeviceSounds device={device} tick={0} actions={actions} />)
    expect(await screen.findByText(/с прошивки 0.6.0/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Прослушать: Слово услышано'))
    expect(actions.fetchSound).toHaveBeenCalledWith(bell.sha256)
  })

  it('подписи и событие sounds', () => {
    expect(sourceText(tone({ tone: 'wake', source: 'device', sound: bell }))).toBe('только здесь: bell.mp3 · 1.2 с')
    expect(deliveryText(tone({ tone: 'wake', delivery: 'offline' }))).toBe('колонка получит его при подключении')
    const state = makeState()
    const next = reduce(state, { type: 'event', event: { kind: 'sounds', data: { device_id: 'a' }, at: 1 } as CoreEvent })
    expect(next.soundsTick).toBe(state.soundsTick + 1)
  })
})
