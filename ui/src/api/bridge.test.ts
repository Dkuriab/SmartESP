import { describe, expect, it, vi } from 'vitest'
import { hasBridge, sendBridge } from './bridge'

function appWindow(flag: unknown = true) {
  const postMessage = vi.fn()
  return { win: { smartespBridge: flag, webkit: { messageHandlers: { smartesp: { postMessage } } } }, postMessage }
}

describe('мост приложения', () => {
  it('есть, только если приложение поставило флаг и обработчик', () => {
    expect(hasBridge(appWindow().win)).toBe(true)
    expect(hasBridge(appWindow('true').win)).toBe(false)
    expect(hasBridge({ smartespBridge: true })).toBe(false)
    expect(hasBridge({})).toBe(false)
  })

  it('шлёт ровно {action}; без моста — ничего', () => {
    const { win, postMessage } = appWindow()
    sendBridge('revealLog', win)
    expect(postMessage).toHaveBeenCalledWith({ action: 'revealLog' })
    const off = appWindow(false)
    sendBridge('openConfig', off.win)
    expect(off.postMessage).not.toHaveBeenCalled()
  })
})
