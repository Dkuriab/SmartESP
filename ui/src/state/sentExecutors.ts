// Последний отправленный список исполнителей. Правка шлёт весь список, а
// настройки в состоянии обновляются только после применения и перечитывания:
// вторая быстрая правка, построенная на них, молча откатила бы первую.
// Поэтому, пока отправленное не применено и не перечитано, правки строятся на нём.
import type { Executor } from './executors'
import type { Action } from './model'

/** Сколько ранних событий о применении помнить (событие может обогнать ответ PATCH). */
const MAX_EARLY = 50

/** Одна отправка: её список и база до неё (чтобы вернуть, если PATCH отклонят). */
export type SentTicket = { list: Executor[]; before: Executor[] | null }

export type SentExecutors = {
  /** База для следующей правки; null — брать из настроек. */
  base(): Executor[] | null
  /** Список уходит в PATCH: следующие правки строятся на нём. */
  sending(list: Executor[]): SentTicket
  /** Ядро приняло правку с этим change_id. */
  accepted(changeId: number): void
  /** PATCH отклонён: база — как до него; других ждущих правок нет — забыть всё. */
  rejected(ticket: SentTicket): void
  /** Действие редьюсера: события о применении, загрузки настроек, переподключение. */
  observe(action: Action): void
}

/**
 * Забывается, когда ядро применило все наши правки (ни одного PATCH без ответа)
 * и пришли настройки, запрошенные после последнего применения; а также при
 * ошибке применения и переподключении.
 */
class SentMemory implements SentExecutors {
  private list: Executor[] | null = null
  /** PATCH без ответа. */
  private inFlight = 0
  /** Принятые, но ещё не применённые change_id. */
  private unapplied = new Set<number>()
  /** Когда применена последняя наша правка. */
  private appliedAt = -Infinity
  /** Когда запрошены последние полученные настройки. */
  private configAt = -Infinity
  /** change_id → ok: события, обогнавшие ответ PATCH. */
  private early = new Map<number, boolean>()

  constructor(private readonly now: () => number) {}

  base(): Executor[] | null {
    return this.list
  }

  sending(list: Executor[]): SentTicket {
    const ticket = { list, before: this.list }
    this.list = list
    this.inFlight += 1
    return ticket
  }

  accepted(id: number): void {
    this.inFlight = Math.max(0, this.inFlight - 1)
    if (this.list === null) return // уже забыто (ошибка применения, переподключение)
    this.unapplied.add(id)
    const ok = this.early.get(id)
    if (ok !== undefined) this.applied(id, ok)
    this.settle()
  }

  rejected(ticket: SentTicket): void {
    this.inFlight = Math.max(0, this.inFlight - 1)
    // после отклонённой ушли новые правки — они уже построены на ней, их список оставляем
    if (this.list === ticket.list) this.list = ticket.before
    if (this.list === null) this.clear()
    else this.settle()
  }

  observe(action: Action): void {
    if (action.type === 'opened') this.clear() // ядро могло перезапуститься
    else if (action.type === 'event' && action.event.kind === 'change_applied') this.onApplied(action.event.data)
    else if (action.type === 'loaded' && action.resource === 'config') {
      this.configAt = Math.max(this.configAt, action.requestedAt ?? -Infinity)
      this.settle()
    }
  }

  private onApplied(data: Record<string, unknown>): void {
    const id = data.change_id
    if (this.list === null || typeof id !== 'number') return
    if (!this.unapplied.has(id)) return this.remember(id, data.ok === true)
    this.applied(id, data.ok === true)
    this.settle()
  }

  /** Ошибка применения — забыть всё; иначе правка больше не ждёт. */
  private applied(id: number, ok: boolean): void {
    if (!ok) return this.clear()
    this.unapplied.delete(id)
    this.early.delete(id)
    this.appliedAt = this.now()
  }

  /** Ничего не ждёт и настройки новее последнего применения — база снова из настроек. */
  private settle(): void {
    const idle = this.inFlight === 0 && this.unapplied.size === 0
    if (this.list !== null && idle && this.configAt >= this.appliedAt) this.clear()
  }

  private remember(id: number, ok: boolean): void {
    this.early.set(id, ok)
    if (this.early.size > MAX_EARLY) this.early.delete(this.early.keys().next().value as number)
  }

  private clear(): void {
    this.list = null
    this.unapplied.clear()
    this.early.clear()
  }
}

/** now — часы, те же, что у загрузчика (requestedAt). */
export function createSentExecutors(now: () => number = Date.now): SentExecutors {
  return new SentMemory(now)
}
