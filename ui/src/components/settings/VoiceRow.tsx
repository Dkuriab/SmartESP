// Строка каталога голосов: подпись, размер, скачивание, образцы, выбор.
import { useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { Download, Voice } from '../../state/model'
import { playBlob, progressText } from './voice'

type Actions = Pick<CoreActions, 'downloadVoice' | 'previewVoice' | 'selectVoice'>
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

export default function VoiceRow({ voice, download, applying, actions }: Props) {
  const [playing, setPlaying] = useState<string | null>(null)
  const play = async (style: string) => {
    setPlaying(style)
    try {
      await playBlob(await actions.previewVoice(voice.kind, voice.voice, style))
    } catch {
      // ошибку уже показало действие уведомлением
    } finally {
      setPlaying(null)
    }
  }
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
          <button type="button" className="btn small" disabled={applying} onClick={() => void actions.selectVoice(voice.kind, voice.voice)}>
            {applying ? 'Применяется…' : 'Выбрать'}
          </button>
        )}
      </div>
    </li>
  )
}
