// Метки вызовов инструментов хода: зелёная — удался, красная — нет.
import type { Turn } from '../../state/model'

type Used = Turn['tools'][number]

/** Вызовы хода без повторов (инструмент и итог); у старых ходов списка нет. */
export function usedTools(turn: Turn): Used[] {
  const seen = new Set<string>()
  return (turn.tools ?? []).filter((t) => {
    const key = `${t.tool}/${String(t.ok)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/** Метка одного вызова: имя инструмента; в подсказке — коннектор и итог. */
export function ToolTag({ used }: { used: Used }) {
  const title = `${used.connector || 'коннектор неизвестен'} · ${used.ok ? 'удался' : 'не удался'}`
  return (
    <span className={`tag ${used.ok ? 'tool' : 'err'}`} title={title}>
      {`🧩 ${used.tool}`}
    </span>
  )
}
