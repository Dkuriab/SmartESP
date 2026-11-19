// Последний отправленный список исполнителей. Правка шлёт весь список, а
// настройки в состоянии обновляются только после применения и перечитывания:
// вторая быстрая правка, построенная на них, молча откатила бы первую.
// Поэтому, пока отправленное не применено и не перечитано, правки строятся на нём.
import type { Executor } from './executors'
import type { Action } from './model'

/** Сколько ранних событий о применении помнить (событие может обогнать ответ PATCH). */
const MAX_EARLY = 50

export type SentExecutors = {
  /** База для следующей правки; null — брать из настроек. */
  base(): Executor[] | null
  /** Список уходит в PATCH: следующие правки строятся на нём. */
  sending(list: Executor[]): void
  /** Ядро приняло правку с этим change_id. */
  accepted(changeId: number): void
  /** Забыть отправленное (PATCH отклонён и т. п.). */
  clear(): void
  /** Действие редьюсера: события о применении, загрузки настроек, переподключение. */
  observe(action: Action): void
}

/** Запоминает исход применения, забывая самые старые сверх MAX_EARLY. */
function remember(early: Map<number, boolean>, id: number, ok: boolean) {
  early.set(id, ok)
  if (early.size > MAX_EARLY) early.delete(early.keys().next().value as number)
}

/** now — часы, те же, что у загрузчика (requestedAt). */
export function createSentExecutors(now: () => number = Date.now): SentExecutors {
  let list: Executor[] | null = null
  let ids = new Set<number>()
  let last = -1
  let appliedAt: number | null = null
  const early = new Map<number, boolean>()

  function clear() {
    list = null
    ids = new Set()
    last = -1
    appliedAt = null
    early.clear()
  }

  /** Ошибка любой нашей правки — забыть; применена последняя — ждать настроек новее. */
  function applied(id: number, ok: boolean) {
    if (!ok) clear()
    else if (id === last) appliedAt = now()
  }

  function onApplied(data: Record<string, unknown>) {
    const id = data.change_id
    if (list === null || typeof id !== 'number') return
    if (ids.has(id)) applied(id, data.ok === true)
    else remember(early, id, data.ok === true)
  }

  return {
    base: () => list,
    sending(next) {
      list = next
      appliedAt = null
    },
    accepted(id) {
      if (list === null) return
      ids.add(id)
      last = Math.max(last, id)
      const ok = early.get(id)
      if (ok !== undefined) applied(id, ok)
    },
    clear,
    observe(action) {
      if (action.type === 'opened') clear() // ядро могло перезапуститься
      else if (action.type === 'event' && action.event.kind === 'change_applied') onApplied(action.event.data)
      else if (action.type === 'loaded' && action.resource === 'config') {
        if (appliedAt !== null && (action.requestedAt ?? -Infinity) >= appliedAt) clear()
      }
    },
  }
}
