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

/** Аргументы вызова строкой: «{"city": "Тверь"}» → «city: Тверь»; пусто — «без аргументов». */
export function argumentsText(args: Record<string, unknown> | undefined): string {
  const entries = Object.entries(args ?? {})
  if (entries.length === 0) return 'без аргументов'
  return entries.map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`).join(', ')
}

/** Вызов скилла в карточке хода: кто и что спросил, что скилл ответил (ответ — свёрнут). */
export function ToolCall({ used, who }: { used: Used; who: string }) {
  return (
    <details className={`tool-call${used.ok ? '' : ' bad'}`}>
      <summary>
        <span className={`tag ${used.ok ? 'tool' : 'err'}`}>{`🧩 ${used.tool}`}</span>
        <span className="tool-args">{argumentsText(used.arguments)}</span>
      </summary>
      <div className="cap">{`${who} → ${used.connector || 'коннектор неизвестен'}${used.ok ? '' : ' · ошибка'}`}</div>
      <pre className="tool-result">{used.result || 'ответ не сохранён'}</pre>
    </details>
  )
}
