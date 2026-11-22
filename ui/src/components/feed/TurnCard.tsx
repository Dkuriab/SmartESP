// Карточка хода: полный вопрос, пометки, передачи задач, вызовы инструментов и ответ без обрезки.
import type { Turn } from '../../state/model'
import './feed.css'
import type { ExecutorName } from './names'
import { executorName, turnPlace } from './names'
import { formatTime } from './time'
import { ToolCall } from './tools'

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
          {formatTime(turn.at)} · {turnPlace(turn)}
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
        {turn.interruption === 'paused' && <span className="tag p">прервано результатом</span>}
        {turn.interruption === 'resumed' && <span className="tag">продолжение</span>}
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
      {(turn.tools ?? []).length > 0 && (
        <>
          <div className="cap card-label">Скиллы: запрос и ответ</div>
          {(turn.tools ?? []).map((t, i) => (
            <ToolCall key={i} used={t} who={executorName(executors, t.executor)} />
          ))}
        </>
      )}
      <div className="cap card-label">Ответ</div>
      <div className="card-text">{turn.answer || '—'}</div>
    </div>
  )
}
