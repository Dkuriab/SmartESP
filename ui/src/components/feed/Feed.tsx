// Лента ходов (новые сверху) и карточка выбранного хода.
import type { Turn } from '../../state/model'
import TurnCard from './TurnCard'
import TurnRow from './TurnRow'
import './feed.css'

type Props = {
  turns: Turn[]
  selectedId: Turn['turn_id'] | null
  onSelect: (id: Turn['turn_id'] | null) => void
  /** Лента на весь экран (вкладка «Лента»). */
  full?: boolean
}

export default function Feed({ turns, selectedId, onSelect, full = false }: Props) {
  const selected = turns.find((t) => t.turn_id === selectedId)
  return (
    <>
      <div className={`panel feed${full ? ' feed-full' : ''}`}>
        <div className="cap feed-title">Лента</div>
        <div className="feed-list">
          {turns.length === 0 && <div className="empty">Пока нет фраз</div>}
          {turns.map((t) => (
            <TurnRow key={t.turn_id} turn={t} selected={t.turn_id === selectedId} onSelect={onSelect} />
          ))}
        </div>
      </div>
      {selected && <TurnCard turn={selected} full={full} onClose={() => onSelect(null)} />}
    </>
  )
}
