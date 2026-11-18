// Лента ходов: живой ход и слияние с загруженной лентой.
// Ядро нумерует ходы заново в каждом процессе, поэтому turn_id сравниваются
// только среди ходов текущего подключения (currentIds).
import type { Turn } from './model'
import { MAX_TURNS } from './model'

type TurnId = Turn['turn_id']

export type Feed = { turns: Turn[]; currentIds: TurnId[] }

/**
 * Живой ход. Уже известный при этом подключении — заменяется на месте;
 * иначе — в начало ленты (ход с тем же id из прежнего процесса убирается).
 */
export function addTurn(feed: Feed, turn: Turn): Feed {
  const id = turn.turn_id
  if (feed.currentIds.includes(id)) {
    return { ...feed, turns: feed.turns.map((t) => (t.turn_id === id ? turn : t)) }
  }
  const turns = [turn, ...feed.turns.filter((t) => t.turn_id !== id)].slice(0, MAX_TURNS)
  return { turns, currentIds: [id, ...feed.currentIds].slice(0, MAX_TURNS) }
}

/**
 * Загруженная лента (от новых к старым) — главная. Сверху остаются только ходы,
 * пришедшие событиями при текущем подключении, которых в загрузке нет.
 * Ходы прежних подключений отбрасываются.
 */
export function mergeTurns(feed: Feed, loaded: Turn[]): Feed {
  const loadedIds = new Set(loaded.map((t) => t.turn_id))
  const current = new Set(feed.currentIds)
  const live = feed.turns.filter((t) => current.has(t.turn_id) && !loadedIds.has(t.turn_id))
  const turns = [...live, ...loaded].slice(0, MAX_TURNS)
  return { turns, currentIds: turns.map((t) => t.turn_id) }
}
