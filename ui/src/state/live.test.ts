import { describe, expect, it } from 'vitest'
import type { CoreEvent } from '../api/events'
import type { Live } from './live'
import { NO_LIVE, applyLive, quietLive } from './live'

const ids = { turn_id: 7, device_id: 'kitchen' }

function ev(kind: string, data: Record<string, unknown>): CoreEvent {
  return { kind, data: { ...ids, ...data }, at: 1 }
}

function run(...events: CoreEvent[]): Live {
  return events.reduce(applyLive, NO_LIVE)
}

describe('applyLive: исполнители', () => {
  it('думает, затем говорит, done снимает', () => {
    const thinking = run(ev('executor_active', { executor: 'dispatcher', state: 'thinking' }))
    expect(thinking.executors).toEqual({ dispatcher: { state: 'thinking', turn: 'kitchen#7' } })
    const speaking = applyLive(thinking, ev('executor_active', { executor: 'dispatcher', state: 'speaking' }))
    expect(speaking.executors.dispatcher?.state).toBe('speaking')
    const done = applyLive(speaking, ev('executor_active', { executor: 'dispatcher', state: 'done' }))
    expect(done.executors).toEqual({})
  })

  it('конец хода не снимает исполнителя: отложенный ответ ещё думает', () => {
    const live = run(ev('executor_active', { executor: 'big', state: 'thinking' }), ev('turn_finished', {}))
    expect(live.executors.big?.state).toBe('thinking')
  })

  it('done другого хода не снимает исполнителя, занятого новым ходом', () => {
    const second = ev('executor_active', { executor: 'big', state: 'thinking', turn_id: 8 })
    const oldDone = ev('executor_active', { executor: 'big', state: 'done', turn_id: 7 })
    expect(run(second, oldDone).executors.big?.turn).toBe('kitchen#8')
  })

  it('без executor событие пропускается', () => {
    expect(run(ev('executor_active', { state: 'thinking' }))).toBe(NO_LIVE)
  })
})

describe('applyLive: коннекторы', () => {
  const started = ev('tool_call', { executor: 'dispatcher', connector: 'calc', tool: 'calc_add', state: 'started', ok: true })
  const finished = ev('tool_call', { executor: 'dispatcher', connector: 'calc', tool: 'calc_add', state: 'finished', ok: true })

  it('started — в работе, finished — снят', () => {
    expect(run(started).connectors).toEqual({ calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'kitchen#7' } })
    expect(run(started, finished).connectors).toEqual({})
  })

  it('finished чужого вызова не снимает текущий', () => {
    const other = ev('tool_call', { connector: 'calc', tool: 'calc_mul', state: 'finished', ok: true })
    expect(run(started, other).connectors.calc?.tool).toBe('calc_add')
  })

  it('конец хода снимает его инструменты, чужие остаются', () => {
    const elsewhere = { ...started, data: { ...started.data, device_id: 'hall', connector: 'notes' } }
    const live = run(started, elsewhere, ev('turn_finished', {}))
    expect(Object.keys(live.connectors)).toEqual(['notes'])
  })
})

describe('applyLive: старты работы (для подсветки не короче 1,2 с)', () => {
  const started = ev('tool_call', { executor: 'dispatcher', connector: 'calc', tool: 'calc_add', state: 'started' })
  const finished = ev('tool_call', { executor: 'dispatcher', connector: 'calc', tool: 'calc_add', state: 'finished' })
  const thinking = ev('executor_active', { executor: 'dispatcher', state: 'thinking' })

  it('каждый старт получает новый номер; конец старт не стирает', () => {
    const live = run(started, finished)
    expect(live.connectors).toEqual({})
    expect(live.started?.['connector:calc']).toEqual({ seq: 1, value: { tool: 'calc_add', executor: 'dispatcher', turn: 'kitchen#7' } })
    const again = applyLive(live, started)
    expect(again.started?.['connector:calc']?.seq).toBe(2)
    expect(applyLive(again, thinking).started?.['executor:dispatcher']).toMatchObject({ seq: 3, value: { state: 'thinking' } })
  })

  it('quietLive: всё снято, но номера стартов продолжаются', () => {
    const quiet = quietLive(run(started, thinking))
    expect(quiet).toMatchObject({ executors: {}, connectors: {}, started: {} })
    expect(applyLive(quiet, started).started?.['connector:calc']?.seq).toBe(3)
  })
})
