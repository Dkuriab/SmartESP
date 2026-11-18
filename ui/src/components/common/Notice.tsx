// Уведомление: короткий текст, закрывается крестиком.
import type { Notice as NoticeData } from '../../state/model'
import './common.css'

type Props = { notice: NoticeData; onDismiss: () => void }

export default function Notice({ notice, onDismiss }: Props) {
  return (
    <div className={`notice notice-${notice.tone}`} role="status">
      <span className="notice-text">{notice.text}</span>
      <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onDismiss}>
        ×
      </button>
    </div>
  )
}
