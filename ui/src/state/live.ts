// Живая подсветка: какие исполнители и коннекторы работают прямо сейчас (из событий хода).
import type { CoreEvent } from '../api/events'

/** Исполнитель в работе: думает (ждём первый текст) или говорит; turn — ключ хода. */
export type LiveExecutor = { state: 'thinking' | 'speaking'; turn: string }
/** Коннектор в работе: какой инструмент и кто его вызвал. */
export type LiveTool = { tool: string; executor: string; turn: string }

export type Live = {
  executors: Record<string, LiveExecutor>
  connectors: Record<string, LiveTool>
}

export const NO_LIVE: Live = { executors: {}, connectors: {} }

type Data = Record<string, unknown>

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

/** Ключ хода: номера ходов у каждой колонки свои. */
export function turnKey(data: Data): string {
  const id = data.turn_id
  return `${str(data.device_id)}#${typeof id === 'number' || typeof id === 'string' ? id : ''}`
}

function without<T>(map: Record<string, T>, key: string): Record<string, T> {
  const rest = { ...map }
  delete rest[key]
  return rest
}

/** executor_active: thinking/speaking — в работе, done — снять. */
function executorActive(live: Live, data: Data): Live {
  const id = str(data.executor)
  if (!id) return live
  const state = data.state
  if (state === 'thinking' || state === 'speaking') {
    return { ...live, executors: { ...live.executors, [id]: { state, turn: turnKey(data) } } }
  }
  return { ...live, executors: without(live.executors, id) }
}

/** tool_call: started — коннектор в работе; finished — снять, если это тот же вызов. */
function toolCall(live: Live, data: Data): Live {
  const id = str(data.connector)
  if (!id) return live
  const call = { tool: str(data.tool), executor: str(data.executor), turn: turnKey(data) }
  if (data.state === 'started') return { ...live, connectors: { ...live.connectors, [id]: call } }
  const now = live.connectors[id]
  if (!now || now.tool !== call.tool || now.turn !== call.turn) return live
  return { ...live, connectors: without(live.connectors, id) }
}

/**
 * Конец хода: его инструменты уже не работают. Исполнителей снимает их done
 * (ответ «на потом» договаривает после конца хода).
 */
function turnFinished(live: Live, data: Data): Live {
  const key = turnKey(data)
  const connectors = Object.fromEntries(Object.entries(live.connectors).filter(([, c]) => c.turn !== key))
  return { ...live, connectors }
}

/** Применяет событие к живой подсветке; прочие события её не меняют. */
export function applyLive(live: Live, e: CoreEvent): Live {
  switch (e.kind) {
    case 'executor_active':
      return executorActive(live, e.data)
    case 'tool_call':
      return toolCall(live, e.data)
    case 'turn_finished':
      return turnFinished(live, e.data)
    default:
      return live
  }
}
