// Обновление колонки по воздуху: «Обновить прошивку…» (.bin) и ход последнего обновления.
import { useRef } from 'react'
import type { Device } from '../../state/model'

/** Протокол колонки, которая умеет обновляться по воздуху (прошивка 0.5.0+). */
export const UPDATE_PROTOCOL = 4

const WHAT: Record<string, string> = { firmware: 'Прошивка', model: 'Модель слова' }
const ERRORS: Record<string, string> = {
  busy: 'колонка уже обновляется',
  download: 'не скачалась (связь с ядром)',
  size: 'размер не тот или не помещается',
  hash: 'файл повредился по дороге',
  write: 'не записалась во флеш',
  storage: 'нет места для модели',
}

const kb = (bytes: number) => `${Math.round(bytes / 1024)} КБ`

/** Что сказать о последнем обновлении колонки; share — доля для полосы (null — без полосы). */
export function describeUpdate(update: NonNullable<Device['update']>): { text: string; share: number | null; bad: boolean } {
  const what = WHAT[update.what] ?? update.what
  if (update.state === 'sent') return { text: `${what}: отправлено, колонка начинает скачивать…`, share: 0, bad: false }
  if (update.state === 'progress') {
    const share = update.total > 0 ? Math.round((100 * update.done) / update.total) : 0
    return { text: `${what}: скачано ${kb(update.done)} из ${kb(update.total)} (${share} %)`, share, bad: false }
  }
  if (update.state === 'done') return { text: `${what}: записано — колонка перезагружается`, share: null, bad: false }
  return { text: `${what}: не удалось — ${ERRORS[update.error] ?? update.error ?? 'ошибка'}`, share: null, bad: true }
}

type Props = { device: Device; onInstall: (file: File) => void }

export default function DeviceUpdate({ device, onInstall }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const status = device.update ? describeUpdate(device.update) : null
  const running = device.update?.state === 'sent' || device.update?.state === 'progress'
  if (device.protocol < UPDATE_PROTOCOL) {
    return device.connected ? <div className="set-note">Обновление по воздуху — с прошивки 0.5.0: первый раз прошейте её по USB</div> : null
  }
  return (
    <div className="field field-block">
      <span className="cap set-label">Обновление по воздуху</span>
      <input ref={input} type="file" accept=".bin" hidden aria-label="Файл прошивки"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onInstall(file)
          e.target.value = ''
        }} />
      <button type="button" className="btn" disabled={!device.connected || running} onClick={() => input.current?.click()}>
        Обновить прошивку…
      </button>
      {status && <div className={status.bad ? 'set-note bad' : 'set-note'} role="status">{status.text}</div>}
      {status && status.share !== null && <div className="job-bar"><div style={{ width: `${status.share}%` }} /></div>}
      <div className="set-note">Файл .bin — из tools/build.sh (firmware/build/SmartEsp.ino.bin) или Arduino IDE: «Экспорт бинарного файла».</div>
    </div>
  )
}
