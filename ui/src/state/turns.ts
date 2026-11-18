// Лента ходов: добавление живого хода и слияние с загруженной лентой.
import type { Turn } from './model'
import { MAX_TURNS } from './model'

/** Живой ход: в начало ленты; уже известный — заменяется на месте. */
export function addTurn(turns: Turn[], turn: Turn): Turn[] {
  const index = turns.findIndex((t) => t.turn_id === turn.turn_id)
  if (index >= 0) return turns.map((t, i) => (i === index ? turn : t))
  return [turn, ...turns].slice(0, MAX_TURNS)
}

/**
 * Сливает загруженную ленту (от новых к старым) с уже известными ходами.
 * Известные ходы до первого общего с загрузкой — новее загрузки и идут первыми.
 * При первой загрузке все известные ходы пришли событиями — тоже новее.
 * Остальные известные заменяет загрузка: она и есть свежая лента ядра.
 */
export function mergeTurns(current: Turn[], loaded: Turn[], firstLoad: boolean): Turn[] {
  const loadedIds = new Set(loaded.map((t) => t.turn_id))
  const overlap = current.findIndex((t) => loadedIds.has(t.turn_id))
  let newer: Turn[]
  if (overlap >= 0) newer = current.slice(0, overlap)
  else newer = firstLoad ? current : []
  return [...newer, ...loaded].slice(0, MAX_TURNS)
}
