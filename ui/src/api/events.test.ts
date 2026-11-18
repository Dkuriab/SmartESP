import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { connectEvents } from './events'

class FakeWS {
  static all: FakeWS[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  closed = false
  constructor(public url: string) {
    FakeWS.all.push(this)
  }
  close() {
    this.closed = true
  }
  open() {
    this.onopen?.()
  }
  drop(code = 1006) {
    this.onclose?.({ code })
  }
}

function sock(i: number): FakeWS {
  const ws = FakeWS.all[i]
  if (!ws) throw new Error(`нет сокета ${i}`)
  return ws
}

function setup() {
  const handlers = { onEvent: vi.fn(), onOpen: vi.fn(), onClose: vi.fn() }
  const conn = connectEvents('t k', handlers, {
    WebSocketImpl: FakeWS as unknown as typeof WebSocket,
  })
  return { handlers, conn }
}

beforeEach(() => {
  FakeWS.all = []
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

describe('connectEvents', () => {
  it('подключается по адресу с токеном и отдаёт события', () => {
    const { handlers } = setup()
    const ws = sock(0)
    expect(ws.url).toBe(`ws://${location.host}/api/v1/events?token=t%20k`)
    ws.open()
    expect(handlers.onOpen).toHaveBeenCalledTimes(1)
    const ev = { kind: 'turn_finished', data: { turn_id: 1 }, at: 5 }
    ws.onmessage?.({ data: JSON.stringify(ev) })
    expect(handlers.onEvent).toHaveBeenCalledWith(ev)
  })

  it('игнорирует невалидный JSON', () => {
    const { handlers } = setup()
    sock(0).onmessage?.({ data: 'not json' })
    expect(handlers.onEvent).not.toHaveBeenCalled()
  })

  it('переподключается через 1, 2, 5, 5 с', () => {
    const { handlers } = setup()
    for (const [i, delay] of [1000, 2000, 5000, 5000].entries()) {
      sock(i).drop()
      vi.advanceTimersByTime(delay - 1)
      expect(FakeWS.all).toHaveLength(i + 1)
      vi.advanceTimersByTime(1)
      expect(FakeWS.all).toHaveLength(i + 2)
    }
    sock(4).open()
    expect(handlers.onOpen).toHaveBeenCalledTimes(1)
  })

  it('после успешного открытия задержки начинаются заново', () => {
    setup()
    sock(0).drop()
    vi.advanceTimersByTime(1000)
    sock(1).drop()
    vi.advanceTimersByTime(2000)
    sock(2).open()
    sock(2).drop()
    vi.advanceTimersByTime(1000)
    expect(FakeWS.all).toHaveLength(4)
  })

  it('4401 не переподключается и вызывает onClose(4401)', () => {
    const { handlers } = setup()
    sock(0).drop(4401)
    vi.advanceTimersByTime(60000)
    expect(handlers.onClose).toHaveBeenCalledWith(4401)
    expect(FakeWS.all).toHaveLength(1)
  })

  it('обычный обрыв вызывает onClose с кодом', () => {
    const { handlers } = setup()
    sock(0).drop(1006)
    expect(handlers.onClose).toHaveBeenCalledWith(1006)
  })

  it('close() останавливает переподключения', () => {
    const { conn } = setup()
    sock(0).drop()
    conn.close()
    vi.advanceTimersByTime(60000)
    expect(FakeWS.all).toHaveLength(1)
  })

  it('close() закрывает открытое соединение и глушит onClose', () => {
    const { conn, handlers } = setup()
    const ws = sock(0)
    conn.close()
    expect(ws.closed).toBe(true)
    ws.drop()
    vi.advanceTimersByTime(60000)
    expect(FakeWS.all).toHaveLength(1)
    expect(handlers.onClose).not.toHaveBeenCalled()
  })
})
