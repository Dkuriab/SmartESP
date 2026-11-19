import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState, Status } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus, makeVoice } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const voices = [
  makeVoice({ kind: 'piper', voice: 'irina', title: 'Ирина', downloaded: true, current: true }),
  makeVoice({ kind: 'silero', voice: 'xenia', title: 'Ксения', size_mb: 40, downloaded: false }),
  makeVoice({ kind: 'vosk', voice: 'ru', title: 'Vosk русский', size_mb: 900, downloaded: true }),
]

const readyVoice: Status['voice'] = { kind: 'piper', voice: 'irina', state: 'ready', error: null }

function setup(over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({
    config: makeConfig(),
    voices,
    status: makeStatus({ voice: readyVoice }),
    selected: { kind: 'voice', id: 'voice' },
    ...over,
  })
  const view = render(<SettingsPanel state={state} actions={actions} />)
  return { actions, ...view }
}

const row = (title: string) => screen.getByRole('listitem', { name: title })

/** Поддельный Audio: запоминает экземпляры, конец проигрывания — вручную. */
class FakeAudio {
  static last: FakeAudio | null = null
  onended: (() => void) | null = null
  onerror: (() => void) | null = null
  paused = true
  constructor(public src: string) {
    FakeAudio.last = this
  }
  play() {
    this.paused = false
    return Promise.resolve()
  }
  pause() {
    this.paused = true
  }
}

describe('VoiceSettings', () => {
  beforeEach(() => {
    vi.stubGlobal('Audio', FakeAudio)
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('каталог по видам, текущий отмечен, лицензия Silero', () => {
    setup()
    for (const kind of ['Piper', 'Silero', 'Vosk']) expect(screen.getByRole('heading', { name: kind })).toBeInTheDocument()
    expect(within(row('Ирина')).getByText('текущий')).toBeInTheDocument()
    expect(within(row('Ирина')).queryByRole('button', { name: 'Выбрать' })).not.toBeInTheDocument()
    expect(screen.getByText(/только для некоммерческого использования/)).toBeInTheDocument()
  })

  it('голос не скачан: «Скачать» вызывает downloadVoice, «▶» неактивны', async () => {
    const { actions } = setup()
    const r = row('Ксения')
    expect(within(r).getByText('40 МБ')).toBeInTheDocument()
    expect(within(r).getByRole('button', { name: '▶ Обычный' })).toBeDisabled()
    expect(within(r).getByRole('button', { name: '▶ Тихий' })).toBeDisabled()
    await userEvent.click(within(r).getByRole('button', { name: 'Скачать' }))
    expect(actions.downloadVoice).toHaveBeenCalledWith('silero', 'xenia')
  })

  it('ход скачивания из downloads — в процентах, без кнопки «Скачать»', () => {
    setup({ downloads: { 'silero/xenia': { done: 10, total: 40 } } })
    const r = row('Ксения')
    expect(within(r).getByText('25%')).toBeInTheDocument()
    expect(within(r).getByRole('progressbar')).toBeInTheDocument()
    expect(within(r).queryByRole('button', { name: 'Скачать' })).not.toBeInTheDocument()
  })

  it('«Выбрать» вызывает selectVoice', async () => {
    const { actions } = setup()
    await userEvent.click(within(row('Vosk русский')).getByRole('button', { name: 'Выбрать' }))
    expect(actions.selectVoice).toHaveBeenCalledWith('vosk', 'ru')
  })

  it('при pending «Выбрать» показывает «Применяется…»', () => {
    setup({ pending: { 2: 'Голос irina' } })
    expect(within(row('Vosk русский')).getByRole('button', { name: 'Применяется…' })).toBeDisabled()
  })

  it('«▶ Тихий» проигрывает образец, на время — «играет…», по окончании URL освобождается', async () => {
    const { actions } = setup()
    vi.mocked(actions.previewVoice).mockResolvedValue(new Blob(['x']))
    await userEvent.click(within(row('Ирина')).getByRole('button', { name: '▶ Тихий' }))
    expect(actions.previewVoice).toHaveBeenCalledWith('piper', 'irina', 'quiet')
    expect(FakeAudio.last?.src).toBe('blob:x')
    expect(within(row('Ирина')).getByRole('button', { name: 'играет…' })).toBeDisabled()
    await act(async () => FakeAudio.last?.onended?.())
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x')
    expect(within(row('Ирина')).getByRole('button', { name: '▶ Тихий' })).toBeEnabled()
  })

  it('новый образец останавливает прежний', async () => {
    const { actions } = setup()
    vi.mocked(actions.previewVoice).mockResolvedValue(new Blob(['x']))
    await userEvent.click(within(row('Ирина')).getByRole('button', { name: '▶ Обычный' }))
    const first = FakeAudio.last
    await userEvent.click(within(row('Vosk русский')).getByRole('button', { name: '▶ Обычный' }))
    expect(first?.paused).toBe(true)
    expect(FakeAudio.last).not.toBe(first)
    expect(within(row('Ирина')).getByRole('button', { name: '▶ Обычный' })).toBeEnabled()
    expect(within(row('Vosk русский')).getByRole('button', { name: 'играет…' })).toBeInTheDocument()
  })

  it('уход с панели останавливает проигрывание и освобождает URL', async () => {
    const { actions, unmount } = setup()
    vi.mocked(actions.previewVoice).mockResolvedValue(new Blob(['x']))
    await userEvent.click(within(row('Ирина')).getByRole('button', { name: '▶ Обычный' }))
    unmount()
    expect(FakeAudio.last?.paused).toBe(true)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x')
  })

  it('образец пришёл после ухода с панели — не играет', async () => {
    const { actions, unmount } = setup()
    let answer: (b: Blob) => void = () => {}
    vi.mocked(actions.previewVoice).mockReturnValue(new Promise<Blob>((r) => (answer = r)))
    await userEvent.click(within(row('Ирина')).getByRole('button', { name: '▶ Обычный' }))
    FakeAudio.last = null
    unmount()
    await act(async () => answer(new Blob(['x'])))
    expect(FakeAudio.last).toBeNull()
  })

  it('ошибка образца сбрасывает «играет…»', async () => {
    const { actions } = setup()
    vi.mocked(actions.previewVoice).mockRejectedValue(new Error('нет'))
    await userEvent.click(within(row('Ирина')).getByRole('button', { name: '▶ Обычный' }))
    expect(within(row('Ирина')).getByRole('button', { name: '▶ Обычный' })).toBeEnabled()
    expect(screen.queryByText('играет…')).not.toBeInTheDocument()
  })

  it('состояние текущего: качается N%', () => {
    const voice: Status['voice'] = { kind: 'silero', voice: 'xenia', state: 'downloading', error: null }
    setup({ status: makeStatus({ voice }), downloads: { 'silero/xenia': { done: 1, total: 2 } } })
    expect(screen.getByText('качается 50%')).toBeInTheDocument()
  })

  it('состояние текущего: ошибка с текстом', () => {
    const voice: Status['voice'] = { kind: 'piper', voice: 'irina', state: 'failed', error: 'нет места' }
    setup({ status: makeStatus({ voice }) })
    expect(screen.getByText('ошибка: нет места')).toBeInTheDocument()
  })

  it('состояние текущего: готов', () => {
    setup()
    expect(screen.getByText('готов')).toBeInTheDocument()
  })

  it('каталог ещё не загружен — «Загрузка…»', () => {
    setup({ voices: null })
    expect(screen.getByText('Загрузка…')).toBeInTheDocument()
  })
})
