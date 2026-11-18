// Редьюсер состояния интерфейса: чистая функция, без сети.
import { applyEvent } from './eventRules'
import type { Action, CoreState, Loaded } from './model'
import { mergeTurns } from './turns'

function applyLoaded(state: CoreState, loaded: Loaded): CoreState {
  switch (loaded.resource) {
    case 'turns':
      return {
        ...state,
        turns: mergeTurns(state.turns, loaded.data, !state.turnsLoaded),
        turnsLoaded: true,
      }
    case 'status':
      return { ...state, status: loaded.data }
    case 'config':
      return { ...state, config: loaded.data }
    case 'voices':
      return { ...state, voices: loaded.data }
    case 'models':
      return { ...state, models: loaded.data }
  }
}

/** Изменение отправлено; если его итог уже пришёл событием — не ждём. */
function changeSent(state: CoreState, changeId: number, description: string): CoreState {
  if (state.applied.includes(changeId)) return state
  return { ...state, pending: { ...state.pending, [changeId]: description } }
}

/** Новое состояние по действию; связь пропала — данные остаются. */
export function reduce(state: CoreState, action: Action): CoreState {
  switch (action.type) {
    case 'loaded':
      return applyLoaded(state, action)
    case 'event':
      return applyEvent(state, action.event)
    case 'connection':
      return { ...state, connection: action.connection }
    case 'select':
      return { ...state, selected: action.selected }
    case 'selectTurn':
      return { ...state, selectedTurnId: action.turnId }
    case 'changeSent':
      return changeSent(state, action.changeId, action.description)
    case 'notice':
      return { ...state, notice: action.notice }
    case 'dismissNotice':
      return { ...state, notice: null }
  }
}
