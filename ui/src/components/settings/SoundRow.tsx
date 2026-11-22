// Один сигнал колонки: откуда звук, доставка и кнопки «Прослушать», «Заменить…», «Встроенный».
import { useRef } from 'react'
import type { DeviceSound } from '../../state/soundActions'
import { TONE_LABELS, deliveryText, sourceText } from './sounds'

type Props = {
  sound: DeviceSound
  /** Заменить и вернуть встроенный нельзя (колонка не умеет звуки, идёт запрос). */
  locked: boolean
  /** Есть что возвращать: свой звук на колонке или (для всех) общий. */
  canReset: boolean
  onPlay: () => void
  onReplace: (file: File) => void
  onReset: () => void
}

const ACCEPT = '.mp3,.wav,.ogg,.oga,.opus,.m4a,.flac,audio/*'

export default function SoundRow({ sound, locked, canReset, onPlay, onReplace, onReset }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const label = TONE_LABELS[sound.tone]
  const delivery = deliveryText(sound)
  return (
    <li className="sound-row">
      <div className="sound-head">
        <span className="sound-name">{label}</span>
        <span className="sound-source cut">{sourceText(sound)}</span>
      </div>
      {delivery && <div className={sound.delivery === 'failed' ? 'set-note bad' : 'set-note'}>{delivery}</div>}
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
        <button type="button" className="btn small" disabled={locked || !canReset} onClick={onReset}>
          Встроенный
        </button>
      </div>
    </li>
  )
}
