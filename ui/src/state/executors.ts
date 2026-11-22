// Правка списка исполнителей: чистые функции над executors из настроек.
import type { Reasoning } from '../schema/blocks'
import { asList } from '../schema/blocks'

/** Промпт нового исполнителя: отвечать голосом (тот же, что у «Большой модели» по умолчанию в ядре). */
export const VOICE_PROMPT =
  'Ты отвечаешь голосом через колонку: по-русски, без разметки и списков, связно, до 6–8 предложений.'

/** Исполнитель в форме config.yaml. */
export type Executor = Record<string, unknown>

/** Правка исполнителя: только заданные поля (undefined не затирает). */
export type ExecutorPatch = {
  name?: string
  /** ollama — модель на Mac; cloud — облачный сервис (раздел cloud настроек). */
  kind?: string
  model?: string
  description?: string
  systemPrompt?: string
  reasoning?: Reasoning
  /** Род ассистента (у входного исполнителя — это он сам). */
  gender?: 'male' | 'female'
}

const FIELDS: Record<keyof ExecutorPatch, string> = {
  name: 'name',
  kind: 'kind',
  model: 'model',
  description: 'description',
  systemPrompt: 'system_prompt',
  reasoning: 'reasoning',
  gender: 'gender',
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

/** Номер N первого свободного id executor-N. */
function freeNumber(list: Executor[]): number {
  const ids = new Set(list.map((e) => e.id))
  let n = 1
  while (ids.has(`executor-${n}`)) n += 1
  return n
}

/** id, который получит следующий исполнитель (executor-N). */
export function nextExecutorId(list: Executor[]): string {
  return `executor-${freeNumber(list)}`
}

/** Новый исполнитель: первый свободный executor-N, модель входного, голосовой промпт. */
export function withAdded(list: Executor[]): Executor[] {
  const n = freeNumber(list)
  const entry = list.find((e) => e.entry === true)
  const added: Executor = {
    id: `executor-${n}`,
    name: `Исполнитель ${n}`,
    model: entry?.model ?? '',
    entry: false,
    system_prompt: VOICE_PROMPT,
    description: '',
    delegates: [],
  }
  if (typeof entry?.kind === 'string') added.kind = entry.kind
  return [...list, added]
}

/** Без исполнителя id и без ссылок на него; входного и неизвестного убрать нельзя (тот же список). */
export function withRemoved(list: Executor[], id: string): Executor[] {
  const target = list.find((e) => e.id === id)
  if (!target || target.entry === true) return list
  return list
    .filter((e) => e.id !== id)
    .map((e) => (delegatesOf(e).some((d) => d.to === id) ? { ...e, delegates: delegatesOf(e).filter((d) => d.to !== id) } : e))
}

/**
 * Включает/выключает связь from → to; when задаёт условие (у существующей связи — меняет).
 * Связь на себя или с неизвестным исполнителем — тот же список без изменений.
 */
export function withLink(list: Executor[], from: string, to: string, enabled: boolean, when: string): Executor[] {
  const known = (id: string) => list.some((e) => e.id === id)
  if (from === to || !known(from) || !known(to)) return list
  return list.map((e) => {
    if (e.id !== from) return e
    const rest = delegatesOf(e).filter((d) => d.to !== to)
    return { ...e, delegates: enabled ? [...rest, { to, when }] : rest }
  })
}
