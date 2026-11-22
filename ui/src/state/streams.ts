// Музыка на колонках: потоки по колонкам из GET /streams, событий stream и ответов на управление.
import type { CoreEvent } from '../api/events'
import type { CoreState, Stream } from './model'

const STATES = new Set<Stream['state']>(['idle', 'playing', 'paused'])

/** Список ядра → словарь по колонке. */
export function streamsById(list: Stream[]): Record<string, Stream> {
  return Object.fromEntries(list.map((s) => [s.device_id, s]))
}

/** Поток колонки заменяется целиком. */
export function setStream(state: CoreState, stream: Stream): CoreState {
  return { ...state, streams: { ...state.streams, [stream.device_id]: stream } }
}

/** Событие stream: данные — поток колонки; без колонки или с неизвестным состоянием — мимо. */
export function applyStreamEvent(state: CoreState, e: CoreEvent): CoreState {
  const { device_id: id, state: phase } = e.data
  if (typeof id !== 'string' || !id || typeof phase !== 'string' || !STATES.has(phase as Stream['state'])) return state
  return setStream(state, e.data as unknown as Stream)
}
