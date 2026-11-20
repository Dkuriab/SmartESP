import { describe, expect, it } from 'vitest'
import { CLICK_AFTER_DRAG_MS, createClickGuard } from './clickGuard'

describe('createClickGuard: клик сразу после перетаскивания не выбирает узел', () => {
  it('клик без перетаскивания проходит', () => {
    expect(createClickGuard(() => 0).allowsClick()).toBe(true)
  })

  it('клик, пришедший с отпусканием после перетаскивания, гасится; следующий проходит', () => {
    let now = 1000
    const guard = createClickGuard(() => now)
    guard.dragged()
    expect(guard.allowsClick()).toBe(false)
    now += CLICK_AFTER_DRAG_MS
    expect(guard.allowsClick()).toBe(true)
  })
})
