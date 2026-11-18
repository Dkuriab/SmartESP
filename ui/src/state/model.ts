// Типы состояния интерфейса и действий редьюсера.
import type { CoreEvent } from '../api/events'
import type { components } from '../api/schema'

type Schemas = components['schemas']
export type Status = Schemas['StatusOut']
export type Config = Schemas['ConfigOut']
export type Voice = Schemas['VoiceOut']
export type Model = Schemas['ModelOut']
export type Turn = Schemas['TurnOut']
export type Device = Schemas['DeviceOut']

export type Connection = 'connecting' | 'online' | 'offline' | 'unauthorized'

export type Selection = {
  kind: 'device' | 'stage' | 'dispatcher' | 'voice'
  id: string
}

export type Notice = { text: string; tone: 'ok' | 'error' }

/** Ход скачивания голоса; total неизвестен — null. */
export type Download = { done: number; total: number | null }

export type CoreState = {
  connection: Connection
  status: Status | null
  config: Config | null
  voices: Voice[] | null
  models: Model[] | null
  /** Ходы от новых к старым, не больше MAX_TURNS. */
  turns: Turn[]
  selected: Selection | null
  selectedTurnId: number | string | null
  /** Ключ — "kind/voice". */
  downloads: Record<string, Download>
  /** change_id → описание изменения, пока оно применяется. */
  pending: Record<number, string>
  notice: Notice | null
  // --- служебное, компоненты не читают ---
  /** Лента уже загружалась хотя бы раз (для слияния с живыми ходами). */
  turnsLoaded: boolean
  /** Голоса ("kind/voice"), о неудаче которых уже сообщили. */
  voiceFailures: Record<string, true>
  /** Недавно применённые change_id: событие может прийти раньше ответа PATCH. */
  applied: number[]
}

/** Загруженный ресурс: имя и данные в форме ответа API. */
export type Loaded =
  | { resource: 'status'; data: Status }
  | { resource: 'config'; data: Config }
  | { resource: 'voices'; data: Voice[] }
  | { resource: 'models'; data: Model[] }
  | { resource: 'turns'; data: Turn[] }

export type Action =
  | ({ type: 'loaded' } & Loaded)
  | { type: 'event'; event: CoreEvent }
  | { type: 'connection'; connection: Connection }
  | { type: 'select'; selected: Selection | null }
  | { type: 'selectTurn'; turnId: number | string | null }
  | { type: 'changeSent'; changeId: number; description: string }
  | { type: 'notice'; notice: Notice }
  | { type: 'dismissNotice' }

export const MAX_TURNS = 100
/** Сколько последних применённых change_id помнить. */
export const MAX_APPLIED = 50

/** Начальное состояние; без токена сразу «unauthorized». */
export function initialState(connection: Connection = 'connecting'): CoreState {
  return {
    connection,
    status: null,
    config: null,
    voices: null,
    models: null,
    turns: [],
    selected: null,
    selectedTurnId: null,
    downloads: {},
    pending: {},
    notice: null,
    turnsLoaded: false,
    voiceFailures: {},
    applied: [],
  }
}
