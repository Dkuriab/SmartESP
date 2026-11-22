// Блоки ядра (колонки, обработчики, диспетчер, голос) из состояния: общие для схемы,
// левого списка и панели настроек.
import type { StageEntry } from '../state/actions'
import type { CoreState, Device } from '../state/model'

/** Уровень рассуждения модели перед ответом (как reasoning в ядре). */
export type Reasoning = 'off' | 'low' | 'medium' | 'high'

/** Уровни по порядку; первый — по умолчанию. */
export const REASONING_LEVELS: readonly Reasoning[] = ['off', 'low', 'medium', 'high']

/** Известные обработчики: выключенный показывается серым и без связей. */
export const KNOWN_STAGES = [
  { kind: 'whisper_detect', title: 'Шёпот', icon: '🤫', description: 'замечает, что вопрос сказан шёпотом (видно в ленте)' },
  { kind: 'clock', title: 'Время', icon: '🕒', description: 'добавляет к вопросу местное время и дату, чтобы ответ не выдумывал их' },
  { kind: 'system', title: 'Система', icon: '🧭', description: 'подсказывает модели, что сейчас в работе и какие навыки подключены' },
]

/** Флажок обработчика в его записи stages (по умолчанию выключен). */
export type StageOption = { key: 'quiet_reply'; label: string; hint: string }

/** Флажки обработчиков по kind: показываются в панели настроек обработчика. */
export const STAGE_OPTIONS: Record<string, StageOption[]> = {
  whisper_detect: [{ key: 'quiet_reply', label: 'Отвечать тише на шёпот', hint: 'Это не настоящий шёпот: голос просто тише' }],
}

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

/** Значение флажка обработчика из настроек; нет обработчика или флажка — false. */
export function stageOption(state: CoreState, kind: string, key: StageOption['key']): boolean {
  return configuredStages(state).find((s) => s.kind === kind)?.[key] === true
}

/** Новый список stages: у записи kind флажок key = value, остальное как было. */
export function stagesWithOption(state: CoreState, kind: string, key: StageOption['key'], value: boolean): StageEntry[] {
  return configuredStages(state).map((s) => (s.kind === kind ? { ...s, [key]: value } : s))
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
  /** ollama — модель на Mac; cloud — облачный сервис. */
  kind: string
  model: string
  description: string
  systemPrompt: string
  reasoning: Reasoning
  /** Род ассистента; важен у входного исполнителя (он и есть ассистент). */
  gender: 'male' | 'female'
  entry: boolean
  links: LinkItem[]
}

/** Уровень рассуждения из настроек; нет или неизвестен — off (как в ядре). */
function reasoningOf(value: unknown): Reasoning {
  return REASONING_LEVELS.find((level) => level === value) ?? 'off'
}

/** Исполнители из настроек, входной первым. */
export function listExecutors(state: CoreState): ExecutorItem[] {
  const raw = asList(state.config?.effective.executors)
  const str = (v: unknown) => (typeof v === 'string' ? v : '')
  const description = (id: string) => str(raw.find((e) => e.id === id)?.description)
  const items = raw.map((e) => ({
    id: str(e.id),
    name: str(e.name),
    kind: str(e.kind) || 'ollama',
    model: str(e.model),
    description: str(e.description),
    systemPrompt: str(e.system_prompt),
    reasoning: reasoningOf(e.reasoning),
    gender: (e.gender === 'female' ? 'female' : 'male') as ExecutorItem['gender'],
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
