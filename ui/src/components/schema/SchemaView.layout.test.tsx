// Регрессия «схема пропадает, пока не переключишь вкладки» и перетаскивание:
// ResizeObserver и размеры элементов подменены, чтобы React Flow измерил узлы как в браузере.
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import { LIVE_FADE_MS, LIVE_MIN_MS } from '../../schema/linger'
import type { CoreState } from '../../state/model'
import SchemaView from './SchemaView'

const observers = new Set<ObserverMock>()
class ObserverMock {
  targets = new Set<Element>()
  constructor(private callback: ResizeObserverCallback) {
    observers.add(this)
  }
  observe(el: Element) {
    this.targets.add(el)
  }
  unobserve(el: Element) {
    this.targets.delete(el)
  }
  disconnect() {
    this.targets.clear()
  }
  fire() {
    const entries = [...this.targets].map((target) => ({ target, contentRect: { width: 800, height: 600 } }))
    if (entries.length) this.callback(entries as unknown as ResizeObserverEntry[], this as unknown as ResizeObserver)
  }
}
/** Браузер измерил всё, что наблюдается. */
const measure = () => act(() => observers.forEach((o) => o.fire()))

const realObserver = globalThis.ResizeObserver
beforeAll(() => {
  globalThis.ResizeObserver = ObserverMock as unknown as typeof ResizeObserver
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get: () => 200 })
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, get: () => 50 })
})
afterAll(() => {
  globalThis.ResizeObserver = realObserver
  delete (HTMLElement.prototype as { offsetWidth?: number }).offsetWidth
  delete (HTMLElement.prototype as { offsetHeight?: number }).offsetHeight
})
afterEach(() => {
  observers.clear()
  vi.useRealTimers()
})

const hiddenNodes = () =>
  Array.from(document.querySelectorAll<HTMLElement>('.react-flow__node')).filter((n) => n.style.visibility === 'hidden').length
const draw = (state: CoreState) => <div style={{ width: 800, height: 600 }}><SchemaView state={state} actions={makeActions()} /></div>

describe('SchemaView: схема не пропадает при обновлении данных', () => {
  it('опрос status (новое состояние) не прячет измеренные узлы и стрелки', () => {
    const state = makeState({ config: makeConfig() })
    const view = render(draw(state))
    measure()
    expect(document.querySelectorAll('.react-flow__node').length).toBeGreaterThan(3)
    expect(hiddenNodes()).toBe(0)
    const edges = document.querySelectorAll('.react-flow__edge').length
    expect(edges).toBeGreaterThan(0)
    // свежий status: те же узлы, новые объекты; ResizeObserver повторно не срабатывает
    view.rerender(draw({ ...state, status: makeStatus({ uptime_s: 99 }) }))
    expect(hiddenNodes()).toBe(0)
    expect(document.querySelectorAll('.react-flow__edge').length).toBe(edges)
  })

  it('есть кнопка «Расставить заново»', () => {
    render(draw(makeState({ config: makeConfig() })))
    fireEvent.click(screen.getByRole('button', { name: 'Расставить заново' }))
    expect(screen.getByText('Кухня')).toBeInTheDocument()
  })
})

describe('SchemaView: живая подсветка держится и гаснет', () => {
  it('вызов на миллисекунду светится LIVE_MIN_MS, затем гаснет и снимается', () => {
    vi.useFakeTimers()
    const connectors = [{ id: 'calc', name: 'Калькулятор', command: 'uv', enabled: true }]
    const idle = makeState({ config: makeConfig({ connectors }) })
    const busy = { ...idle, live: { executors: {}, connectors: { calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' } } } }
    const view = render(draw(busy))
    view.rerender(draw(idle))
    const card = () => screen.getByText('Калькулятор').closest('.node')
    expect(card()).toHaveClass('live')
    act(() => void vi.advanceTimersByTime(LIVE_MIN_MS))
    expect(card()).toHaveClass('fading')
    act(() => void vi.advanceTimersByTime(LIVE_FADE_MS))
    expect(card()).not.toHaveClass('live')
    expect(card()).not.toHaveClass('fading')
  })

  it('обрыв связи снимает подсветку сразу', () => {
    const connectors = [{ id: 'calc', name: 'Калькулятор', command: 'uv', enabled: true }]
    const idle = makeState({ config: makeConfig({ connectors }) })
    const busy = { ...idle, live: { executors: {}, connectors: { calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' } } } }
    const view = render(draw(busy))
    view.rerender(draw({ ...idle, connection: 'offline' }))
    expect(screen.getByText('Калькулятор').closest('.node')).not.toHaveClass('live')
  })
})
