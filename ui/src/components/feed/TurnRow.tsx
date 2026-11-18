// Строка хода: колонка, вопрос, пометки, ответ, стиль, задержки, ошибка.
import type { Turn } from '../../state/model'
import './feed.css'
import { formatTime } from './time'

type Props = { turn: Turn; selected: boolean; onSelect: (id: Turn['turn_id']) => void }

/** Задержки «stt / первый звук», мс; нет данных — прочерк. */
function delays(turn: Turn): string | null {
  if (turn.stt_ms == null && turn.first_audio_ms == null) return null
  return `${turn.stt_ms ?? '—'} / ${turn.first_audio_ms ?? '—'} мс`
}

export default function TurnRow({ turn, selected, onSelect }: Props) {
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
          <span className="cut q" title={turn.text}>
            {turn.text}
          </span>
          {turn.annotations.map((a, i) => (
            <span key={i} className="tag" title={a.source}>
              {a.text}
            </span>
          ))}
          {turn.style === 'quiet' && <span className="tag p">тихо</span>}
          {turn.status === 'error' && <span className="tag err">ошибка</span>}
        </span>
        <span className="cut route" title={turn.answer}>
          {turn.answer}
        </span>
      </span>
      {timing && <span className="timing">{timing}</span>}
    </button>
  )
}
