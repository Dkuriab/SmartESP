// Типы состояния интерфейса и действий редьюсера.
import type { CoreEvent } from '../api/events'
import type { components } from '../api/schema'
import type { Live } from './live'
import { NO_LIVE } from './live'

type Schemas = components['schemas']
export type Status = Schemas['StatusOut']
export type Config = Schemas['ConfigOut']
export type Voice = Schemas['VoiceOut']
export type Model = Schemas['ModelOut']
/** Модель облачного сервиса (цены — $ за 1 млн токенов). */
export type CloudModel = Schemas['CloudModelOut']
/** Модель LM Studio: загружена ли и умеет ли инструменты родно (null — неизвестно). */
export type LmStudioModel = Schemas['LmStudioModelOut']
/** Список моделей LM Studio и ошибка запроса ('' — нет ошибки). */
export type LmStudioList = { models: LmStudioModel[]; error: string }
export type Turn = Schemas['TurnOut']
export type Device = Schemas['DeviceOut']
export type Connector = Schemas['ConnectorOut']
/** Коннектор из GET /connectors: ещё и объявленные им настройки. */
export type ConnectorDetail = Schemas['ConnectorDetailOut']
export type ConnectorSetting = Schemas['ConnectorSettingOut']
/** Задача «В работе»: что ядро или коннектор делает в фоне. */
export type Task = Schemas['TaskOut']
/** Поток звука на колонке (музыка, радио, звук Mac). */
export type Stream = Schemas['StreamOut']
export type StreamAction = Schemas['StreamControlIn']['action']

export type Connection = 'connecting' | 'online' | 'offline' | 'unauthorized'

export type Selection = {
  kind: 'device' | 'stage' | 'dispatcher' | 'executor' | 'voice' | 'connector'
  id: string
}

export type Notice = { text: string; tone: 'ok' | 'error' }

/** Файл на колонке: загружается (ждём ответа ядра) или играет. */
export type FilePhase = 'sending' | 'playing'

/** Ход скачивания голоса; total неизвестен — null. */
export type Download = { done: number; total: number | null }

export type CoreState = {
  connection: Connection
  status: Status | null
  config: Config | null
  voices: Voice[] | null
  models: Model[] | null
  /** Коннекторы с настройками (GET /connectors); null — не загружены. */
  connectors: ConnectorDetail[] | null
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
  /** Кто работает прямо сейчас: исполнители и коннекторы (из событий хода). */
  live: Live
  /** Файлы на колонках: device_id → фаза; нет ключа — файл не играет. */
  files: Record<string, FilePhase>
  /** «В работе»: идущие и недавно законченные задачи (GET /tasks и события task_*). */
  tasks: Task[]
  /** Растёт с каждым событием sounds: панель звуков колонки перечитывает обзор. */
  soundsTick: number
  /** Музыка на колонках: device_id → поток (GET /streams и события stream). */
  streams: Record<string, Stream>
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
  | { resource: 'connectors'; data: ConnectorDetail[] }
  | { resource: 'tasks'; data: Task[] }
  | { resource: 'streams'; data: Stream[] }

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
  /** Модель выгружена из памяти Ollama: до следующего status её нет в списке. */
  | { type: 'modelUnloaded'; name: string }
  /** Фаза файла на колонке (null — не играет); onlyFrom — менять, только если сейчас эта фаза. */
  | { type: 'filePhase'; deviceId: string; phase: FilePhase | null; onlyFrom?: FilePhase }
  /** Поток колонки из ответа ядра на управление (событие stream придёт тоже). */
  | { type: 'stream'; stream: Stream }

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
    connectors: null,
    turns: [],
    selected: null,
    selectedTurnId: null,
    downloads: {},
    pending: {},
    notice: null,
    restarting: false,
    live: NO_LIVE,
    files: {},
    tasks: [],
    soundsTick: 0,
    streams: {},
    currentTurnIds: [],
    pendingSince: {},
    voiceFailures: {},
    applied: [],
  }
}
