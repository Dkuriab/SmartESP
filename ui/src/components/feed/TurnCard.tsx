// Карточка хода: полный вопрос, пометки и ответ без обрезки.
import type { Turn } from '../../state/model'
import './feed.css'
import { formatTime } from './time'

type Props = { turn: Turn; onClose: () => void }

export default function TurnCard({ turn, onClose }: Props) {
  return (
    <div className="panel turn-card" role="dialog" aria-label="Ход">
      <div className="card-head">
        <span className="cap">
          {formatTime(turn.at)} · {turn.device_name || turn.device_id}
        </span>
        <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="card-text">{turn.text}</div>
      <div className="line">
        {turn.annotations.map((a, i) => (
          <span key={i} className="tag" title={a.source}>
            {a.text}
          </span>
        ))}
      </div>
      <div className="cap card-label">Ответ</div>
      <div className="card-text">{turn.answer || '—'}</div>
    </div>
  )
}
