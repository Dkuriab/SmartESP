// Правила применения событий ядра к состоянию интерфейса.
import type { CoreEvent } from '../api/events'
import type { CoreState, Device, Status, Turn } from './model'
import { MAX_APPLIED } from './model'
import { applyFileEvent } from './files'
import { applyLive } from './live'
import { applyEchoEvent } from './echo'
import { applyStreamEvent } from './streams'
import { applyTaskEvent } from './tasks'
import { addTurn } from './turns'

type Data = Record<string, unknown>

function str(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

function voiceKey(data: Data): string {
  return `${str(data.kind)}/${str(data.voice)}`
}

/** Меняет одну колонку в status.devices; неизвестную добавляет. */
function upsertDevice(status: Status, id: string, patch: Partial<Device>): Status {
  const known = status.devices.some((d) => d.device_id === id)
  const devices = known
    ? status.devices.map((d) => (d.device_id === id ? { ...d, ...patch } : d))
    : [
        ...status.devices,
        { device_id: id, name: id, connected: false, remote: '', fw: '', last_seen: null, protocol: 0, volume: 50, ...patch },
      ]
  return { ...status, devices }
}

function deviceEvent(state: CoreState, e: CoreEvent): CoreState {
  if (!state.status) return state // придёт вместе с загрузкой status
  const id = str(e.data.device_id)
  if (!id) return state
  const patch: Partial<Device> =
    e.kind === 'device_connected'
      ? {
          name: str(e.data.name, id) || id,
          remote: str(e.data.remote),
          fw: str(e.data.fw),
          connected: true,
          last_seen: e.at,
          // старое ядро протокол не шлёт: тогда оставляем известный
          ...(typeof e.data.protocol === 'number' ? { protocol: e.data.protocol } : {}),
        }
      : { connected: false, last_seen: e.at }
  return { ...state, status: upsertDevice(state.status, id, patch) }
}

function voiceDownload(state: CoreState, data: Data): CoreState {
  const done = typeof data.done === 'number' ? data.done : 0
  const total = typeof data.total === 'number' ? data.total : null
  return { ...state, downloads: { ...state.downloads, [voiceKey(data)]: { done, total } } }
}

/** Итог скачивания: повторный неуспех того же голоса уведомления не даёт. */
function voiceReady(state: CoreState, data: Data): CoreState {
  const key = voiceKey(data)
  const downloads = { ...state.downloads }
  delete downloads[key]
  const failures = { ...state.voiceFailures }
  const wasFailed = failures[key] === true
  delete failures[key]
  const voice = str(data.voice, key)
  if (data.ok === true) {
    const notice = { text: `Голос ${voice} готов`, tone: 'ok' as const }
    return { ...state, downloads, voiceFailures: failures, notice }
  }
  const voiceFailures = { ...failures, [key]: true as const }
  if (wasFailed) return { ...state, downloads, voiceFailures }
  const reason = str(data.error)
  const text = reason ? `Голос ${voice} не готов: ${reason}` : `Голос ${voice} не готов`
  return { ...state, downloads, voiceFailures, notice: { text, tone: 'error' } }
}

/** Итог изменения: ok — «Применено», иначе текст ошибки (null и "" — нет ошибки). */
function changeApplied(state: CoreState, data: Data): CoreState {
  const id = data.change_id
  if (typeof id !== 'number') return state
  const pending = { ...state.pending }
  delete pending[id]
  const pendingSince = { ...state.pendingSince }
  delete pendingSince[id]
  const applied = [...state.applied, id].slice(-MAX_APPLIED)
  const error = str(data.error)
  const notice =
    data.ok === true
      ? { text: 'Применено', tone: 'ok' as const }
      : { text: error || 'Не удалось применить изменение', tone: 'error' as const }
  return { ...state, pending, pendingSince, applied, notice }
}

function turnFinished(state: CoreState, turn: Turn): CoreState {
  // ядро до живой подсветки не шлёт tools
  const feed = addTurn({ turns: state.turns, currentIds: state.currentTurnIds }, { ...turn, tools: turn.tools ?? [] })
  return { ...state, turns: feed.turns, currentTurnIds: feed.currentIds }
}

function coreState(state: CoreState, data: Data): CoreState {
  const value = data.state
  if (!state.status || (value !== 'warming' && value !== 'ready' && value !== 'stopping')) return state
  return { ...state, status: { ...state.status, state: value } }
}

/** device_update: ход обновления колонки по воздуху — сразу в status (без ожидания опроса). */
function deviceUpdate(state: CoreState, e: CoreEvent): CoreState {
  const id = str(e.data.device_id)
  if (!state.status || !id) return state
  const { what, state: phase, done, total, error, at } = e.data
  if (typeof done !== 'number' || typeof total !== 'number' || typeof at !== 'number') return state
  const update = { what: str(what), state: str(phase), done, total, error: str(error), at }
  const devices = state.status.devices.map((d) => (d.device_id === id ? { ...d, update } : d))
  return { ...state, status: { ...state.status, devices } }
}

/** Применяет событие ядра; неизвестное событие состояние не меняет. */
export function applyEvent(state: CoreState, e: CoreEvent): CoreState {
  switch (e.kind) {
    case 'turn_finished':
      return turnFinished({ ...state, live: applyLive(state.live, e) }, e.data as unknown as Turn)
    case 'executor_active':
    case 'tool_call':
      return { ...state, live: applyLive(state.live, e) }
    case 'device_connected':
    case 'device_disconnected':
      return deviceEvent(state, e)
    case 'device_update':
      return deviceUpdate(state, e)
    case 'device_echo':
      return applyEchoEvent(state, e)
    case 'voice_download':
      return voiceDownload(state, e.data)
    case 'voice_ready':
      return voiceReady(state, e.data)
    case 'change_applied':
      return changeApplied(state, e.data)
    case 'core_state':
      return coreState(state, e.data)
    case 'playback_started':
    case 'playback_finished':
      return applyFileEvent(state, e)
    case 'sounds':
      return { ...state, soundsTick: state.soundsTick + 1 }
    case 'task_started':
    case 'task_updated':
    case 'task_finished':
      return applyTaskEvent(state, e)
    case 'stream':
      return applyStreamEvent(state, e)
    default:
      return state
  }
}
