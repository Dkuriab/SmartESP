// Строка каталога голосов: подпись, размер, скачивание, образцы, выбор.
import { useEffect, useRef, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { Download, Voice } from '../../state/model'
import { playBlob, progressText, stopPlayback } from './voice'

type Actions = Pick<CoreActions, 'downloadVoice' | 'previewVoice' | 'selectVoice' | 'showNotice'>
type Props = { voice: Voice; download?: Download; applying: boolean; actions: Actions }

const STYLES: Array<[string, string]> = [
  ['normal', '▶ Обычный'],
  ['quiet', '▶ Тихий'],
]

/** «скачан», ход скачивания или кнопка «Скачать». */
function Availability({ voice, download, actions }: Omit<Props, 'applying'>) {
  const [asking, setAsking] = useState(false)
  if (voice.downloaded) return <span className="voice-ok">скачан</span>
  if (download) {
    return (
      <span className="voice-progress">
        <progress max={download.total ?? undefined} value={download.total ? download.done : undefined} />
        <span>{progressText(download)}</span>
      </span>
    )
  }
  const start = async () => {
    setAsking(true)
    try {
      // ход дальше приходит событиями voice_download
      await actions.downloadVoice(voice.kind, voice.voice)
    } finally {
      setAsking(false)
    }
  }
  return (
    <button type="button" className="btn small" disabled={asking} onClick={() => void start()}>
      Скачать
    </button>
  )
}

const REFUSED = { text: 'Не удалось воспроизвести образец', tone: 'error' as const }

/** Образец голоса: какой стиль играет и запуск; уход строки с экрана останавливает звук. */
function usePreview(voice: Voice, { previewVoice, showNotice }: Actions) {
  const [playing, setPlaying] = useState<string | null>(null)
  // строка на экране и играет ли её образец
  const mounted = useRef(true)
  const mine = useRef(false)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (mine.current) stopPlayback()
    }
  }, [])
  const play = async (style: string) => {
    setPlaying(style)
    try {
      const blob = await previewVoice(voice.kind, voice.voice, style)
      if (!mounted.current) return
      mine.current = true
      await playBlob(blob, () => showNotice(REFUSED))
    } catch {
      // ошибку уже показало действие уведомлением
    } finally {
      mine.current = false
      setPlaying(null)
    }
  }
  return { playing, play }
}

export default function VoiceRow({ voice, download, applying, actions }: Props) {
  const { playing, play } = usePreview(voice, actions)
  return (
    <li className="voice" aria-label={voice.title}>
      <div className="voice-head">
        <span className="voice-title" title={voice.title}>{voice.title}</span>
        {voice.current && <span className="voice-current">текущий</span>}
        <span className="voice-size">{Math.round(voice.size_mb)} МБ</span>
      </div>
      <div className="voice-actions">
        <Availability voice={voice} download={download} actions={actions} />
        {STYLES.map(([style, label]) => (
          <button key={style} type="button" className="chip" disabled={!voice.downloaded || playing !== null} onClick={() => void play(style)}>
            {playing === style ? 'играет…' : label}
          </button>
        ))}
        {!voice.current && (
          <button type="button" className="btn small" disabled={applying || !voice.downloaded} onClick={() => void actions.selectVoice(voice.kind, voice.voice)}>
            {applying ? 'Применяется…' : 'Выбрать'}
          </button>
        )}
        {!voice.current && !voice.downloaded && <span className="voice-hint">сначала скачайте</span>}
      </div>
    </li>
  )
}
