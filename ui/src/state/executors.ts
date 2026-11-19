// Правка списка исполнителей: чистые функции над executors из настроек.
import { asList } from '../schema/blocks'

/** Исполнитель в форме config.yaml. */
export type Executor = Record<string, unknown>

/** Правка исполнителя: только заданные поля (undefined не затирает). */
export type ExecutorPatch = { name?: string; model?: string; description?: string; systemPrompt?: string }

const FIELDS: Record<keyof ExecutorPatch, string> = {
  name: 'name',
  model: 'model',
  description: 'description',
  systemPrompt: 'system_prompt',
}

/** Ссылки исполнителя в форме config.yaml. */
function delegatesOf(e: Executor): Record<string, unknown>[] {
  return asList(e.delegates)
}

/** Список исполнителей из настроек; null — настроек нет или входного нет. */
export function executorsOf(effective: Record<string, unknown> | undefined): Executor[] | null {
  const list = asList(effective?.executors)
  return list.some((e) => e.entry === true) ? list : null
}

/** Правка исполнителя id; остальные без изменений. */
export function withUpdated(list: Executor[], id: string, patch: ExecutorPatch): Executor[] {
  const changes: Record<string, unknown> = {}
  for (const [key, field] of Object.entries(FIELDS)) {
    const value = patch[key as keyof ExecutorPatch]
    if (value !== undefined) changes[field] = value
  }
  return list.map((e) => (e.id === id ? { ...e, ...changes } : e))
}

/** Новый исполнитель: первый свободный executor-N, модель входного. */
export function withAdded(list: Executor[]): Executor[] {
  const ids = new Set(list.map((e) => e.id))
  let n = 1
  while (ids.has(`executor-${n}`)) n += 1
  const entry = list.find((e) => e.entry === true)
  const added: Executor = {
    id: `executor-${n}`,
    name: `Исполнитель ${n}`,
    model: entry?.model ?? '',
    entry: false,
    system_prompt: '',
    description: '',
    delegates: [],
  }
  if (typeof entry?.kind === 'string') added.kind = entry.kind
  return [...list, added]
}

/** Без исполнителя id и без ссылок на него; входного убрать нельзя (список прежний). */
export function withRemoved(list: Executor[], id: string): Executor[] {
  if (list.find((e) => e.id === id)?.entry === true) return list
  return list
    .filter((e) => e.id !== id)
    .map((e) => (delegatesOf(e).some((d) => d.to === id) ? { ...e, delegates: delegatesOf(e).filter((d) => d.to !== id) } : e))
}

/** Включает/выключает связь from → to; when задаёт условие (у существующей связи — меняет). */
export function withLink(list: Executor[], from: string, to: string, enabled: boolean, when: string): Executor[] {
  return list.map((e) => {
    if (e.id !== from) return e
    const rest = delegatesOf(e).filter((d) => d.to !== to)
    return { ...e, delegates: enabled ? [...rest, { to, when }] : rest }
  })
}
