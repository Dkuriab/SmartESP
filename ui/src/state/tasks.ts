// «В работе»: задачи из событий task_* и их вид для списка (время, срок, угасание законченных).
import type { CoreEvent } from '../api/events'
import type { CoreState, Task } from './model'

/** Сколько мс законченная задача ещё видна в списке (последние секунды — угасает). */
export const FINISHED_VISIBLE_MS = 30_000
/** Последние столько мс видимости законченная задача угасает. */
export const FADE_MS = 5_000
/** Больше задач список не держит. */
const MAX_TASKS = 50

const STATUSES = new Set<Task['status']>(['running', 'done', 'failed', 'cancelled'])

/** Задача из данных события; без ключа или с неизвестным состоянием — null. */
function parseTask(data: Record<string, unknown>): Task | null {
  const { key, status, started_at: startedAt } = data
  if (typeof key !== 'string' || !key || typeof startedAt !== 'number') return null
  if (typeof status !== 'string' || !STATUSES.has(status as Task['status'])) return null
  return data as unknown as Task
}

/** Событие task_*: задача заменяется на месте по ключу, новая — в конец идущих. */
export function applyTaskEvent(state: CoreState, e: CoreEvent): CoreState {
  const task = parseTask(e.data)
  if (!task) return state
  const known = state.tasks.some((t) => t.key === task.key)
  const tasks = known ? state.tasks.map((t) => (t.key === task.key ? task : t)) : [...state.tasks, task]
  return { ...state, tasks: tasks.slice(-MAX_TASKS) }
}

/** Задачи для списка на момент nowMs: идущие (старые первыми), затем недавно законченные. */
export function visibleTasks(tasks: Task[], nowMs: number): Task[] {
  const running = tasks.filter((t) => t.status === 'running').sort((a, b) => a.started_at - b.started_at)
  const finished = tasks
    .filter((t) => t.status !== 'running' && nowMs - (t.finished_at ?? 0) * 1000 < FINISHED_VISIBLE_MS)
    .sort((a, b) => (b.finished_at ?? 0) - (a.finished_at ?? 0))
  return [...running, ...finished]
}

/** Законченная задача угасает: последние FADE_MS своей видимости. */
export function fading(task: Task, nowMs: number): boolean {
  return task.status !== 'running' && nowMs - (task.finished_at ?? 0) * 1000 > FINISHED_VISIBLE_MS - FADE_MS
}

/** Длительность в секундах коротко: «45 с», «3 мин», «1 ч 05 мин». */
export function shortDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} с`
  const minutes = Math.floor(s / 60)
  if (minutes < 60) return `${minutes} мин`
  return `${Math.floor(minutes / 60)} ч ${String(minutes % 60).padStart(2, '0')} мин`
}

/** Что показать о времени задачи: идёт столько-то и сколько до срока, или итог. */
export function taskTiming(task: Task, nowMs: number): string {
  const now = nowMs / 1000
  if (task.status === 'done') return 'готово'
  if (task.status === 'failed') return 'не удалось'
  if (task.status === 'cancelled') return 'отменено'
  const elapsed = `идёт ${shortDuration(now - task.started_at)}`
  if (task.eta == null) return elapsed
  const left = task.eta - now
  return left > 0 ? `${elapsed} · ещё ${shortDuration(left)}` : `${elapsed} · срок прошёл`
}

/** Источник для людей: «ответ модели», имя коннектора или как есть. */
export function sourceLabel(source: string, connectorName: (id: string) => string | undefined): string {
  if (source === 'late_answer') return 'ответ модели'
  if (source.startsWith('connector:')) {
    const id = source.slice('connector:'.length)
    return connectorName(id) ?? id
  }
  return source
}
