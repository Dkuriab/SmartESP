// Блоки ядра (колонки, обработчики, диспетчер, голос) из состояния: общие для схемы,
// левого списка и панели настроек.
import type { StageEntry } from '../state/actions'
import type { CoreState, Device } from '../state/model'

/** Известные обработчики: выключенный показывается серым и без связей. */
export const KNOWN_STAGES = [
  { kind: 'whisper_detect', title: 'Шёпот', icon: '🤫', description: 'отвечает тихо, если вопрос сказан шёпотом' },
]

/** Обработчик в списке: включён ли он в настройках. */
export type StageItem = { kind: string; title: string; icon: string; description: string; enabled: boolean }

/** Входной исполнитель (диспетчер) из настроек. */
export type DispatcherInfo = { model: string; systemPrompt: string }

export function asList(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((e): e is Record<string, unknown> => typeof e === 'object' && e !== null) : []
}

/** Колонки: из status, плюс известные только настройкам (ни разу не подключались). */
export function listDevices(state: CoreState): Device[] {
  const list = [...(state.status?.devices ?? [])]
  const cfg = state.config?.effective.devices
  if (cfg && typeof cfg === 'object' && !Array.isArray(cfg)) {
    for (const [id, v] of Object.entries(cfg)) {
      if (list.some((d) => d.device_id === id)) continue
      const name = (v as { name?: unknown } | null)?.name
      list.push({ device_id: id, name: typeof name === 'string' ? name : '', connected: false, remote: '', fw: '' })
    }
  }
  return list
}

/** Обработчики из настроек в их форме (с timeout_ms и прочим). */
function configuredStages(state: CoreState): StageEntry[] {
  return asList(state.config?.effective.stages).map((s) => ({ ...s, kind: String(s.kind) }))
}

/** Включённые обработчики по порядку, затем известные выключенные. */
export function listStages(state: CoreState): StageItem[] {
  const configured = configuredStages(state).map((s) => s.kind)
  const kinds = [...configured, ...KNOWN_STAGES.map((k) => k.kind).filter((k) => !configured.includes(k))]
  return kinds.map((kind) => {
    const known = KNOWN_STAGES.find((k) => k.kind === kind)
    return { kind, title: known?.title ?? kind, icon: known?.icon ?? '⚙️', description: known?.description ?? '', enabled: configured.includes(kind) }
  })
}

/** Новый список stages: включение добавляет {kind} (остальное заполнит ядро), выключение убирает. */
export function stagesWith(state: CoreState, kind: string, on: boolean): StageEntry[] {
  const rest = configuredStages(state).filter((s) => s.kind !== kind)
  return on ? [...rest, { kind }] : rest
}

export function dispatcherInfo(state: CoreState): DispatcherInfo | null {
  const entry = asList(state.config?.effective.executors).find((e) => e.entry === true)
  if (!entry) return null
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  return { model: str(entry.model), systemPrompt: str(entry.system_prompt) }
}

/** Текущий голос «вид · голос»: живой из status, иначе из настроек; нет — null. */
export function voiceLabel(state: CoreState): string | null {
  const live = state.status?.voice
  const tts = state.config?.effective.tts as { kind?: unknown; voice?: unknown } | undefined
  const kind = live?.kind ?? tts?.kind
  const voice = live?.kind ? live.voice : tts?.voice
  return kind ? `${String(kind)} · ${String(voice ?? '')}` : null
}

/** Идёт ли применение изменения: есть ожидающие change_id или ядро само применяет. */
export function isApplying(state: CoreState): boolean {
  return Object.keys(state.pending).length > 0 || !!state.status?.applying
}
