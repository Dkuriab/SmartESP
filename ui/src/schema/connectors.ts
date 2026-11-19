// Коннекторы (MCP) для схемы, списка и панели; модели в памяти Ollama.
import type { CoreState } from '../state/model'
import { asList, isApplying } from './blocks'

export type ConnectorStateName = 'starting' | 'ready' | 'failed' | 'disabled' | 'unknown'

/** Коннектор: из настроек (вкл/выкл, окружение) и из status (состояние, инструменты, ошибка). */
export type ConnectorItem = {
  id: string
  name: string
  enabled: boolean
  state: ConnectorStateName
  tools: string[]
  error: string
  /** Окружение из настроек; значения секретов скрыты. */
  env: Array<{ key: string; value: string }>
}

export const CONNECTOR_STATES: Record<ConnectorStateName, string> = {
  starting: 'запускается',
  ready: 'готов',
  failed: 'ошибка',
  disabled: 'выключен',
  unknown: 'нет сведений',
}

const SECRET = /TOKEN|KEY|SECRET|PASSWORD/i
export const HIDDEN = '••••••'

/** Значение для показа: у ключей-секретов (TOKEN, KEY, SECRET, PASSWORD) скрыто. */
export function shownValue(key: string, value: string): string {
  return SECRET.test(key) && value !== '' ? HIDDEN : value
}

const str = (v: unknown) => (typeof v === 'string' ? v : '')

function envOf(raw: unknown): Array<{ key: string; value: string }> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return []
  return Object.entries(raw as Record<string, unknown>).map(([key, v]) => ({ key, value: shownValue(key, str(v)) }))
}

/** Коннекторы в порядке настроек, затем известные только ядру. */
export function listConnectors(state: CoreState): ConnectorItem[] {
  const live = state.status?.connectors ?? []
  const items: ConnectorItem[] = asList(state.config?.effective.connectors).map((c) => {
    const id = str(c.id)
    const now = live.find((x) => x.id === id)
    const enabled = c.enabled !== false
    return {
      id,
      name: str(c.name) || now?.name || id,
      enabled,
      state: now?.state ?? (enabled ? 'unknown' : 'disabled'),
      tools: now?.tools ?? [],
      error: now?.error ?? '',
      env: envOf(c.env),
    }
  })
  for (const c of live) {
    if (items.some((x) => x.id === c.id)) continue
    items.push({ id: c.id, name: c.name, enabled: c.state !== 'disabled', state: c.state, tools: c.tools, error: c.error ?? '', env: [] })
  }
  return items
}

/** Новый список connectors для PATCH: у коннектора id меняется только enabled. */
export function connectorsWith(state: CoreState, id: string, on: boolean): Record<string, unknown>[] {
  return asList(state.config?.effective.connectors).map((c) => (c.id === id ? { ...c, enabled: on } : c))
}

/** Переключать коннекторы нельзя: правка применяется или настройки ещё не загружены. */
export function connectorsLocked(state: CoreState): boolean {
  return isApplying(state) || state.config === null
}

/** Имя модели без тега — с «:latest» (так её показывает Ollama). */
function fullName(model: string): string {
  const last = model.split('/').pop() ?? model
  return last.includes(':') ? model : `${model}:latest`
}

/** Модель сейчас загружена в память Ollama (по status.ollama.loaded). */
export function modelInMemory(state: CoreState, model: string): boolean {
  if (!model) return false
  const name = fullName(model)
  return (state.status?.ollama.loaded ?? []).some((m) => fullName(m) === name)
}
