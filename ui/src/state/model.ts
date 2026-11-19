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
  kind: 'device' | 'stage' | 'dispatcher' | 'executor' | 'voice'
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
  /** Перезапуск попросили: кнопка ждёт переподключения к ядру. */
  restarting: boolean
  // --- служебное, компоненты не читают ---
  /**
   * turn_id ходов, полученных при текущем подключении (событием или загрузкой).
   * Ядро нумерует ходы заново в каждом процессе, поэтому id из прежних
   * подключений с новыми не сравниваются.
   */
  currentTurnIds: Array<number | string>
  /** change_id → когда пришёл ответ PATCH (мс); для сверки со status.applying. */
  pendingSince: Record<number, number>
  /** Голоса ("kind/voice"), о неудаче которых уже сообщили. */
  voiceFailures: Record<string, true>
  /**
   * change_id, применённые при текущем подключении: событие может прийти
   * раньше ответа PATCH. Ядро нумерует изменения заново в каждом процессе.
   */
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
  /** requestedAt — когда ушёл запрос (мс); нужен для status. */
  | ({ type: 'loaded'; requestedAt?: number } & Loaded)
  /** WebSocket (пере)подключился: связь есть, ядро могло смениться. */
  | { type: 'opened' }
  | { type: 'event'; event: CoreEvent }
  | { type: 'connection'; connection: Connection }
  | { type: 'select'; selected: Selection | null }
  | { type: 'selectTurn'; turnId: number | string | null }
  /** at — когда пришёл ответ PATCH (мс). */
  | { type: 'changeSent'; changeId: number; description: string; at: number }
  /** Пользователь просит скачать голос: его прежний неуспех снова будет показан. */
  | { type: 'downloadRequested'; kind: string; voice: string }
  | { type: 'notice'; notice: Notice }
  | { type: 'dismissNotice' }
  /** Просьба о перезапуске отправлена (on) или не удалась. */
  | { type: 'restarting'; on: boolean }

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
    restarting: false,
    currentTurnIds: [],
    pendingSince: {},
    voiceFailures: {},
    applied: [],
  }
}
