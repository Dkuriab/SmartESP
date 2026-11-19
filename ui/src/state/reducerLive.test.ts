import { describe, expect, it } from 'vitest'
import type { CoreEvent } from '../api/events'
import { makeTurn } from '../components/fixtures'
import type { CoreState } from './model'
import { initialState } from './model'
import { reduce } from './reducer'

function ev(kind: string, data: Record<string, unknown>, at = 100): CoreEvent {
  return { kind, data, at }
}

function apply(state: CoreState, ...events: CoreEvent[]): CoreState {
  return events.reduce((s, event) => reduce(s, { type: 'event', event }), state)
}

const turn = (id: number) => makeTurn(id, { device_id: 'aa:bb' })

describe('reduce: живая подсветка', () => {
  const thinking = ev('executor_active', { turn_id: 1, device_id: 'aa:bb', executor: 'dispatcher', state: 'thinking' })
  const tool = ev('tool_call', { turn_id: 1, device_id: 'aa:bb', executor: 'dispatcher', connector: 'calc', tool: 'calc_add', state: 'started', ok: true })

  it('события хода попадают в live', () => {
    const s = apply(initialState(), thinking, tool)
    expect(s.live.executors.dispatcher?.state).toBe('thinking')
    expect(s.live.connectors.calc?.tool).toBe('calc_add')
  })

  it('конец хода снимает его инструменты и кладёт ход в ленту', () => {
    const s = apply(initialState(), tool, ev('turn_finished', { ...turn(1) }))
    expect(s.live.connectors).toEqual({})
    expect(s.turns[0]?.turn_id).toBe(1)
  })

  it('ход от старого ядра без tools получает пустой список', () => {
    const old: Record<string, unknown> = { ...turn(2) }
    delete old.tools
    expect(apply(initialState(), ev('turn_finished', old)).turns[0]?.tools).toEqual([])
  })

  it('переподключение сбрасывает live', () => {
    const s = reduce(apply(initialState(), thinking, tool), { type: 'opened' })
    expect(s.live).toEqual({ executors: {}, connectors: {} })
  })
})
