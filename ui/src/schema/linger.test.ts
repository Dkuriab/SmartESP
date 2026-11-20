import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Live } from '../state/live'
import { NO_LIVE } from '../state/live'
import { LIVE_FADE_MS, LIVE_MIN_MS, NO_GLOW, createLinger } from './linger'

const calc: Live = { executors: {}, connectors: { calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' } } }
const thinking: Live = { executors: { dispatcher: { state: 'thinking', turn: 'a#1' } }, connectors: {} }

describe('createLinger: живая подсветка держится и гаснет', () => {
  let now = 0
  beforeEach(() => {
    now = 1000
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())
  const make = () => {
    const linger = createLinger(() => now)
    const seen = vi.fn()
    linger.subscribe(seen)
    return { linger, seen }
  }
  const tick = (ms: number) => {
    now += ms
    vi.advanceTimersByTime(ms)
  }

  it('вызов на миллисекунду всё равно светится не меньше LIVE_MIN_MS, потом гаснет и пропадает', () => {
    const { linger } = make()
    linger.update(calc)
    tick(5)
    linger.update(NO_LIVE)
    expect(linger.snapshot().live.connectors.calc?.tool).toBe('calc_add')
    expect(linger.snapshot().fading.size).toBe(0)
    tick(LIVE_MIN_MS - 10)
    expect(linger.snapshot().fading.size).toBe(0)
    tick(10)
    expect([...linger.snapshot().fading]).toEqual(['connector:calc'])
    expect(linger.snapshot().live.connectors.calc).toBeDefined()
    tick(LIVE_FADE_MS)
    expect(linger.snapshot().live).toEqual(NO_LIVE)
    expect(linger.snapshot().fading.size).toBe(0)
  })

  it('долгая работа гаснет сразу после конца (минимум уже прошёл)', () => {
    const { linger } = make()
    linger.update(thinking)
    tick(3000)
    linger.update(NO_LIVE)
    expect([...linger.snapshot().fading]).toEqual(['executor:dispatcher'])
    tick(LIVE_FADE_MS)
    expect(linger.snapshot().live.executors).toEqual({})
  })

  it('новое состояние того же исполнителя обновляет подпись', () => {
    const { linger } = make()
    linger.update(thinking)
    linger.update({ executors: { dispatcher: { state: 'speaking', turn: 'a#1' } }, connectors: {} })
    expect(linger.snapshot().live.executors.dispatcher?.state).toBe('speaking')
  })

  it('снова заработал во время угасания — снова живой', () => {
    const { linger } = make()
    linger.update(calc)
    linger.update(NO_LIVE)
    tick(LIVE_MIN_MS + 100)
    expect(linger.snapshot().fading.has('connector:calc')).toBe(true)
    linger.update(calc)
    expect(linger.snapshot().fading.size).toBe(0)
    linger.update(NO_LIVE)
    tick(LIVE_MIN_MS - 1)
    expect(linger.snapshot().fading.size).toBe(0)
  })

  it('clear (обрыв связи) снимает всё сразу и сообщает подписчику', () => {
    const { linger, seen } = make()
    linger.update(calc)
    seen.mockClear()
    linger.clear()
    expect(linger.snapshot().live).toEqual(NO_LIVE)
    expect(seen).toHaveBeenCalled()
    tick(LIVE_MIN_MS + LIVE_FADE_MS)
    expect(linger.snapshot().live).toEqual(NO_LIVE)
  })

  it('снимок не меняется без изменений; после отписки таймеры не срабатывают', () => {
    const linger = createLinger(() => now)
    const seen = vi.fn()
    const off = linger.subscribe(seen)
    const first = linger.snapshot()
    expect(linger.snapshot()).toBe(first)
    linger.update(calc)
    linger.update(NO_LIVE)
    off()
    seen.mockClear()
    tick(LIVE_MIN_MS + LIVE_FADE_MS)
    expect(seen).not.toHaveBeenCalled()
  })

  const tool = { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' }
  /** Старт и конец вызова пришли в одном кадре: в live вызова уже нет, остался только старт. */
  const flash = (seq: number): Live => ({ executors: {}, connectors: {}, seq, started: { 'connector:calc': { seq, value: tool } } })

  it('старт и конец в одном кадре: вызов всё равно светится LIVE_MIN_MS и гаснет', () => {
    const { linger } = make()
    linger.update(flash(1))
    expect(linger.snapshot().live.connectors.calc).toEqual(tool)
    expect(linger.snapshot().fading.size).toBe(0)
    tick(LIVE_MIN_MS)
    expect(linger.snapshot().fading.has('connector:calc')).toBe(true)
    tick(LIVE_FADE_MS)
    expect(linger.snapshot()).toBe(NO_GLOW)
    linger.update(flash(1)) // тот же старт ещё раз не зажигает
    expect(linger.snapshot()).toBe(NO_GLOW)
    linger.update(flash(2))
    expect(linger.snapshot().live.connectors.calc).toEqual(tool)
  })

  it('старты, бывшие до появления схемы, не зажигаются; после обрыва новые — зажигаются', () => {
    const linger = createLinger(() => now, flash(4))
    linger.subscribe(() => {})
    linger.update(flash(4))
    expect(linger.snapshot()).toBe(NO_GLOW)
    linger.clear()
    linger.update(flash(5))
    expect(linger.snapshot().live.connectors.calc).toEqual(tool)
  })
})

