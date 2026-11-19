// Строка хода: колонка, вопрос, пометки, передачи, ответ, стиль, задержки, ошибка.
import type { Turn } from '../../state/model'
import './feed.css'
import type { ExecutorName } from './names'
import { executorName } from './names'
import { formatTime } from './time'

type Props = { turn: Turn; executors: ExecutorName[]; selected: boolean; onSelect: (id: Turn['turn_id']) => void }

/** Задержки «stt / первый звук», мс; нет данных — прочерк. */
function delays(turn: Turn): string | null {
  if (turn.stt_ms == null && turn.first_audio_ms == null) return null
  return `${turn.stt_ms ?? '—'} / ${turn.first_audio_ms ?? '—'} мс`
}

/** Цели передач хода по порядку, без повторов. */
function targets(turn: Turn): string[] {
  return [...new Set(turn.delegations.map((d) => d.to))]
}

export default function TurnRow({ turn, executors, selected, onSelect }: Props) {
  const timing = delays(turn)
  return (
    <button
      type="button"
      className={`msg${selected ? ' sel' : ''}`}
      aria-pressed={selected}
      onClick={() => onSelect(turn.turn_id)}
    >
      <span className="time">{formatTime(turn.at)}</span>
      <span className="when cut">{turn.device_name || turn.device_id}</span>
      <span className="msg-body">
        <span className="line">
          {turn.kind === 'announcement' ? (
            <>
              <span className="tag p">сам</span>
              <span className="cut q" title={turn.answer}>
                {turn.answer}
              </span>
            </>
          ) : (
            <span className="cut q" title={turn.text}>
              {turn.text}
            </span>
          )}
          {turn.origin === 'listen' && <span className="tag">ответ на вопрос Кузи</span>}
          {turn.annotations.map((a, i) => (
            <span key={i} className="tag" title={a.source}>
              {a.text}
            </span>
          ))}
          {targets(turn).map((to) => (
            <span key={to} className="tag handoff">{`→ ${executorName(executors, to)}`}</span>
          ))}
          {turn.style === 'quiet' && <span className="tag p">тихо</span>}
          {turn.status === 'error' && <span className="tag err">ошибка</span>}
          {turn.status === 'undelivered' && <span className="tag err">не доставлено</span>}
        </span>
        {turn.kind !== 'announcement' && (
          <span className="cut route" title={turn.answer}>
            {turn.answer}
          </span>
        )}
      </span>
      {timing && <span className="timing">{timing}</span>}
    </button>
  )
}
