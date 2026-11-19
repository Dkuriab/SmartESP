// Имена для ленты: исполнители по id из настроек (неизвестный — сам id) и откуда ход.
import type { Turn } from '../../state/model'

/** Исполнитель в той мере, в какой он нужен ленте. */
export type ExecutorName = { id: string; name: string }

/** Имя исполнителя id; нет в списке или без имени — id. */
export function executorName(executors: ExecutorName[], id: string): string {
  return executors.find((e) => e.id === id)?.name || id
}

/** Откуда ход: колонка, а у хода через API — источник («Telegram») и кто спрашивал. */
export function turnPlace(turn: Turn): string {
  const place = turn.device_name || turn.device_id
  return turn.person ? `${place} · ${turn.person}` : place
}
