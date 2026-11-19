// Блоки ядра (колонки, обработчики, диспетчер, голос) из состояния: общие для схемы,
// левого списка и панели настроек.
import type { StageEntry } from '../state/actions'
import type { CoreState, Device } from '../state/model'

/** Известные обработчики: выключенный показывается серым и без связей. */
export const KNOWN_STAGES = [
  { kind: 'whisper_detect', title: 'Шёпот', icon: '🤫', description: 'отвечает тихо, если вопрос сказан шёпотом' },
  { kind: 'clock', title: 'Время', icon: '🕒', description: 'добавляет к вопросу местное время и дату, чтобы ответ не выдумывал их' },
]

/** Обработчик в списке: включён ли он в настройках. */
export type StageItem = { kind: string; title: string; icon: string; description: string; enabled: boolean }

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
      list.push({ device_id: id, name: typeof name === 'string' ? name : '', connected: false, remote: '', fw: '', protocol: 0 })
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

/** Переключать обработчики нельзя: правка применяется или настройки ещё не загружены. */
export function stagesLocked(state: CoreState): boolean {
  return isApplying(state) || state.config === null
}

/** Связь исполнителя: активна, если задано условие или у цели есть описание. */
export type LinkItem = { to: string; when: string; active: boolean }

/** Исполнитель для списка и схемы. */
export type ExecutorItem = {
  id: string
  name: string
  model: string
  description: string
  systemPrompt: string
  entry: boolean
  links: LinkItem[]
}

/** Исполнители из настроек, входной первым. */
export function listExecutors(state: CoreState): ExecutorItem[] {
  const raw = asList(state.config?.effective.executors)
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  const description = (id: string) => str(raw.find((e) => e.id === id)?.description)
  const items = raw.map((e) => ({
    id: str(e.id),
    name: str(e.name),
    model: str(e.model),
    description: str(e.description),
    systemPrompt: str(e.system_prompt),
    entry: e.entry === true,
    links: asList(e.delegates).map((d) => {
      const to = str(d.to)
      const when = str(d.when)
      return { to, when, active: when.trim() !== '' || description(to).trim() !== '' }
    }),
  }))
  return [...items.filter((e) => e.entry), ...items.filter((e) => !e.entry)]
}

/** Модель известна Ollama и не умеет инструменты: исполнитель с ней не передаёт задачи. */
export function modelWithoutTools(state: CoreState, model: string): boolean {
  return state.models?.find((m) => m.name === model)?.supports_tools === false
}

/** Фоновый прогрев исполнителя закончился ошибкой: «модель недоступна». */
export function executorUnavailable(state: CoreState, id: string): boolean {
  return state.status?.executors?.some((x) => x.id === id && !x.ready) ?? false
}
