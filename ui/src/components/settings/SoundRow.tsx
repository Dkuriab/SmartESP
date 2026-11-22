// Один сигнал колонки: какой звук, доставка («на колонке», «ждёт подключения колонки», «ошибка: … ·
// Повторить») и кнопки «Прослушать», «Заменить…», «Встроенный».
import { useRef } from 'react'
import type { DeviceSound } from '../../state/soundActions'
import { TONE_LABELS, deliveryText, soundText } from './sounds'

type Props = {
  sound: DeviceSound
  /** Идёт запрос: менять нельзя. */
  locked: boolean
  onPlay: () => void
  onReplace: (file: File) => void
  onReset: () => void
  onRetry: () => void
}

const ACCEPT = '.mp3,.wav,.ogg,.oga,.opus,.m4a,.flac,audio/*'

export default function SoundRow({ sound, locked, onPlay, onReplace, onReset, onRetry }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const label = TONE_LABELS[sound.tone]
  const failed = sound.delivery === 'failed'
  return (
    <li className="sound-row">
      <div className="sound-head">
        <span className="sound-name">{label}</span>
        <span className="sound-source cut">{soundText(sound)}</span>
      </div>
      <div className={failed ? 'set-note bad' : 'set-note'} role="status" aria-label={`Доставка: ${label}`}>
        {deliveryText(sound)}
        {failed && <> · <button type="button" className="btn btn-plain" onClick={onRetry}>Повторить</button></>}
      </div>
      <div className="sound-buttons">
        <button type="button" className="btn small" aria-label={`Прослушать: ${label}`} onClick={onPlay}>
          ▶ Прослушать
        </button>
        <input ref={input} type="file" accept={ACCEPT} hidden aria-label={`Файл звука: ${label}`}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) onReplace(file)
            e.target.value = ''
          }} />
        <button type="button" className="btn small" disabled={locked} onClick={() => input.current?.click()}>
          Заменить…
        </button>
        <button type="button" className="btn small" disabled={locked || !sound.sound} onClick={onReset}>
          Встроенный
        </button>
      </div>
    </li>
  )
}
