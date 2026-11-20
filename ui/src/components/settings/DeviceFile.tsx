// Файл на колонке: выбор звукового файла, остановка и фаза. Колонке нужен протокол ≥ 3.
import type { ChangeEvent } from 'react'
import { useRef } from 'react'
import type { Device, FilePhase } from '../../state/model'

/** С этой версии протокола колонка принимает звук, начатый ядром. */
export const MIN_SPEECH_PROTOCOL = 3

/** audio/* и расширения: у ogg/opus в macOS (Safari, окно выбора) нет системного «аудио»-типа. */
export const AUDIO_ACCEPT = 'audio/*,.mp3,.wav,.ogg,.oga,.opus,.m4a'

type Props = { device: Device; phase?: FilePhase; onPlay: (file: File) => void; onStop: () => void }

/** Почему файл проиграть нельзя; можно — пусто. */
function blocker(device: Device): string {
  if (!device.connected) return 'Колонка не в сети'
  if (device.protocol < MIN_SPEECH_PROTOCOL) return 'Файлы играют колонки с новой прошивкой'
  return ''
}

function phaseText(phase?: FilePhase): string {
  if (phase === 'sending') return 'Загружается…'
  if (phase === 'playing') return 'Играет'
  return ''
}

export default function DeviceFile({ device, phase, onPlay, onStop }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const why = blocker(device)
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = '' // тот же файл можно выбрать снова
    if (file) onPlay(file)
  }
  return (
    <div className="field-block device-file">
      <span className="lbl">Звук</span>
      <div className="device-file-row">
        <button type="button" className="btn small" disabled={!!why || phase !== undefined} onClick={() => input.current?.click()}>
          Проиграть файл…
        </button>
        <button type="button" className="btn small" disabled={!!why || phase === 'sending'} onClick={onStop}>
          Остановить
        </button>
        <span className="device-file-phase" role="status">{phaseText(phase)}</span>
      </div>
      <input ref={input} type="file" accept={AUDIO_ACCEPT} hidden aria-label="Звуковой файл" onChange={pick} />
      {why && <div className="set-note">{why}</div>}
    </div>
  )
}
