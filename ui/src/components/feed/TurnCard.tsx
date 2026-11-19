// Карточка хода: полный вопрос, пометки, передачи задач и ответ без обрезки.
import type { Turn } from '../../state/model'
import './feed.css'
import type { ExecutorName } from './names'
import { executorName } from './names'
import { formatTime } from './time'

type Props = {
  turn: Turn
  executors: ExecutorName[]
  /** Лента на весь экран: карточка — в её правом нижнем углу. */
  full?: boolean
  onClose: () => void
}

export default function TurnCard({ turn, executors, full = false, onClose }: Props) {
  return (
    <div className={`panel turn-card${full ? ' turn-card-full' : ''}`} role="dialog" aria-label="Ход">
      <div className="card-head">
        <span className="cap">
          {formatTime(turn.at)} · {turn.device_name || turn.device_id}
        </span>
        <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onClose}>
          ×
        </button>
      </div>
      {turn.kind === 'announcement' ? (
        <div className="line">
          <span className="tag p">сам</span>
        </div>
      ) : (
        <div className="card-text">{turn.text}</div>
      )}
      <div className="line">
        {turn.origin === 'listen' && <span className="tag">ответ на вопрос Кузи</span>}
        {turn.status === 'undelivered' && <span className="tag err">не доставлено</span>}
        {turn.annotations.map((a, i) => (
          <span key={i} className="tag" title={a.source}>
            {a.text}
          </span>
        ))}
      </div>
      {turn.delegations.map((d, i) => (
        <div key={i} className="card-text card-handoff">
          {`Передано: ${executorName(executors, d.to)} — ${d.task}${d.auto ? ' (автоматически)' : ''}`}
        </div>
      ))}
      <div className="cap card-label">Ответ</div>
      <div className="card-text">{turn.answer || '—'}</div>
    </div>
  )
}
