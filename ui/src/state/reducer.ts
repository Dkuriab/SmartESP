// Редьюсер состояния интерфейса: чистая функция, без сети.
import { applyEvent } from './eventRules'
import { setFilePhase } from './files'
import { setStream, streamsById } from './streams'
import { quietLive } from './live'
import type { Action, CoreState, Loaded, Status } from './model'
import { mergeTurns } from './turns'

/**
 * Свежий status с applying=false: изменения, ответ на которые пришёл раньше
 * запроса status, уже применены (их change_applied мог потеряться при обрыве).
 */
function settlePending(state: CoreState, status: Status, requestedAt?: number): CoreState {
  if (status.applying || requestedAt === undefined) return state
  const pending = { ...state.pending }
  const pendingSince = { ...state.pendingSince }
  for (const [id, at] of Object.entries(state.pendingSince)) {
    if (at >= requestedAt) continue
    delete pending[Number(id)]
    delete pendingSince[Number(id)]
  }
  return { ...state, pending, pendingSince }
}

function applyLoaded(state: CoreState, loaded: Loaded, requestedAt?: number): CoreState {
  switch (loaded.resource) {
    case 'turns': {
      const feed = mergeTurns({ turns: state.turns, currentIds: state.currentTurnIds }, loaded.data)
      return { ...state, turns: feed.turns, currentTurnIds: feed.currentIds }
    }
    case 'status':
      return settlePending({ ...state, status: loaded.data }, loaded.data, requestedAt)
    case 'config':
      return { ...state, config: loaded.data }
    case 'voices':
      return { ...state, voices: loaded.data }
    case 'models':
      return { ...state, models: loaded.data }
    case 'connectors':
      return { ...state, connectors: loaded.data }
    case 'tasks':
      return { ...state, tasks: loaded.data }
    case 'streams':
      return { ...state, streams: streamsById(loaded.data) }
  }
}

/**
 * (Пере)подключение: ядро могло перезапуститься и начать нумерацию change_id
 * и turn_id заново — сведения о них от прежнего подключения сбрасываются.
 * Изменение, отправленное после этого, снова попадёт в pending. Перезапуск
 * отменяет скачивания без voice_ready — их ход тоже сбрасывается; кнопка
 * перезапуска снова доступна. Живая подсветка и файлы на колонках — заново: пока
 * связи не было, окончания работы могли потеряться.
 */
function opened(state: CoreState): CoreState {
  return {
    ...state,
    connection: 'online',
    pending: {},
    pendingSince: {},
    applied: [],
    currentTurnIds: [],
    downloads: {},
    restarting: false,
    live: quietLive(state.live),
    files: {},
  }
}

/** Повтор скачивания пользователем: его неуспех снова даст уведомление. */
function downloadRequested(state: CoreState, kind: string, voice: string): CoreState {
  const voiceFailures = { ...state.voiceFailures }
  delete voiceFailures[`${kind}/${voice}`]
  return { ...state, voiceFailures }
}

/** Изменение отправлено; если его итог уже пришёл событием — не ждём. */
function changeSent(state: CoreState, changeId: number, description: string, at: number): CoreState {
  if (state.applied.includes(changeId)) return state
  return {
    ...state,
    pending: { ...state.pending, [changeId]: description },
    pendingSince: { ...state.pendingSince, [changeId]: at },
  }
}

/** Выгруженная модель пропадает из status сразу, не дожидаясь следующего опроса. */
function modelUnloaded(state: CoreState, name: string): CoreState {
  const status = state.status
  if (!status) return state
  const loaded = status.ollama.loaded.filter((m) => m !== name)
  return { ...state, status: { ...status, ollama: { ...status.ollama, loaded } } }
}

/** Новое состояние по действию; связь пропала — данные остаются. */
export function reduce(state: CoreState, action: Action): CoreState {
  switch (action.type) {
    case 'loaded':
      return applyLoaded(state, action, action.requestedAt)
    case 'opened':
      return opened(state)
    case 'event':
      return applyEvent(state, action.event)
    case 'connection':
      // без связи окончания работы не придут: подсветка «думает…» иначе осталась бы навсегда
      return { ...state, connection: action.connection, live: action.connection === 'online' ? state.live : quietLive(state.live) }
    case 'select':
      return { ...state, selected: action.selected }
    case 'selectTurn':
      return { ...state, selectedTurnId: action.turnId }
    case 'changeSent':
      return changeSent(state, action.changeId, action.description, action.at)
    case 'downloadRequested':
      return downloadRequested(state, action.kind, action.voice)
    case 'notice':
      return { ...state, notice: action.notice }
    case 'dismissNotice':
      return { ...state, notice: null }
    case 'restarting':
      return { ...state, restarting: action.on }
    case 'modelUnloaded':
      return modelUnloaded(state, action.name)
    case 'stream':
      return setStream(state, action.stream)
    case 'filePhase':
      return setFilePhase(state, action.deviceId, action.phase, action.onlyFrom)
  }
}
