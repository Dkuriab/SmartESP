// Плашка «Нужен перезапуск ядра» с кнопкой.
import './common.css'

type Props = {
  onRestart: () => void
  /** Перезапуск уже попросили: ждём переподключения. */
  restarting: boolean
  /** Связь с ядром есть. */
  online: boolean
}

export default function RestartBanner({ onRestart, restarting, online }: Props) {
  return (
    <div className="banner" role="status">
      <span>Нужен перезапуск ядра</span>
      <button type="button" className="btn" disabled={restarting || !online} onClick={onRestart}>
        {restarting ? 'Перезапускается…' : 'Перезапустить'}
      </button>
    </div>
  )
}
