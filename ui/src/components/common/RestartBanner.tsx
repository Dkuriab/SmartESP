// Плашка «Нужен перезапуск ядра» с кнопкой.
import './common.css'

type Props = { onRestart: () => void }

export default function RestartBanner({ onRestart }: Props) {
  return (
    <div className="banner" role="status">
      <span>Нужен перезапуск ядра</span>
      <button type="button" className="btn" onClick={onRestart}>
        Перезапустить
      </button>
    </div>
  )
}
