// Редьюсер состояния интерфейса: чистая функция, без сети.
import { applyEvent } from './eventRules'
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
  }
}

/**
 * (Пере)подключение: ядро могло перезапуститься и начать нумерацию change_id
 * и turn_id заново — сведения о них от прежнего подключения сбрасываются.
 * Изменение, отправленное после этого, снова попадёт в pending.
 */
function opened(state: CoreState): CoreState {
  return { ...state, connection: 'online', pending: {}, pendingSince: {}, applied: [], currentTurnIds: [] }
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
      return { ...state, connection: action.connection }
    case 'select':
      return { ...state, selected: action.selected }
    case 'selectTurn':
      return { ...state, selectedTurnId: action.turnId }
    case 'changeSent':
      return changeSent(state, action.changeId, action.description, action.at)
    case 'notice':
      return { ...state, notice: action.notice }
    case 'dismissNotice':
      return { ...state, notice: null }
  }
}
