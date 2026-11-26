import type { CoreEvent } from '../api/events'
import type { Stream } from './model'
import { initialState } from './model'
import { reduce } from './reducer'
import { createStreamActions } from './streamActions'
import type { Client } from './actions'

function stream(over: Partial<Stream> = {}): Stream {
  return {
    device_id: 'aa:bb',
    name: 'Кухня',
    available: true,
    state: 'playing',
    title: 'Группа крови',
    index: 0,
    count: 3,
    position_s: 12,
    live: false,
    volume: 0.6,
    error: '',
    ...over,
  }
}

const event = (data: Record<string, unknown>): CoreEvent => ({ kind: 'stream', data, at: 0 })

describe('streams', () => {
  it('загрузка /streams — по колонкам', () => {
    const state = reduce(initialState('online'), { type: 'loaded', resource: 'streams', data: [stream(), stream({ device_id: 'cc' })] })
    expect(Object.keys(state.streams)).toEqual(['aa:bb', 'cc'])
  })

  it('событие stream заменяет поток колонки; мусор — мимо', () => {
    let state = reduce(initialState('online'), { type: 'event', event: event(stream() as unknown as Record<string, unknown>) })
    state = reduce(state, { type: 'event', event: event({ ...stream(), state: 'paused' }) })
    expect(state.streams['aa:bb']?.state).toBe('paused')
    const same = reduce(state, { type: 'event', event: event({ device_id: 'aa:bb', state: 'jumping' }) })
    expect(same).toBe(state)
  })

  it('управление шлёт действие и кладёт ответ ядра', async () => {
    const dispatch = vi.fn()
    const POST = vi.fn().mockResolvedValue({ data: stream({ state: 'paused' }), response: { status: 200 } })
    await createStreamActions({ POST } as unknown as Client, dispatch).controlStream('aa:bb', 'pause')
    expect(POST).toHaveBeenCalledWith('/api/v1/streams/control', { body: { device_id: 'aa:bb', action: 'pause' } })
    expect(dispatch).toHaveBeenCalledWith({ type: 'stream', stream: stream({ state: 'paused' }) })
  })

  it('громкость музыки шлёт долю 0..1 и кладёт ответ ядра', async () => {
    const dispatch = vi.fn()
    const POST = vi.fn().mockResolvedValue({ data: stream({ volume: 0.4 }), response: { status: 200 } })
    await createStreamActions({ POST } as unknown as Client, dispatch).setStreamVolume('aa:bb', 40)
    expect(POST).toHaveBeenCalledWith('/api/v1/streams/volume', { body: { device_id: 'aa:bb', volume: 0.4, delta: 0 } })
    expect(dispatch).toHaveBeenCalledWith({ type: 'stream', stream: stream({ volume: 0.4 }) })
  })
})
