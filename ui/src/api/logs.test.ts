import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { connectLogs, parseLogLine } from './logs'

class FakeWS {
  static all: FakeWS[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  constructor(public url: string) {
    FakeWS.all.push(this)
  }
  close() {}
}

beforeEach(() => {
  FakeWS.all = []
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

describe('журнал ядра', () => {
  it('разбирает строку; не та форма — null', () => {
    expect(parseLogLine('{"at": 5, "level": "ERROR", "text": "сбой"}')).toEqual({ at: 5, level: 'ERROR', text: 'сбой' })
    expect(parseLogLine('{"level": "INFO", "text": "x"}')).toEqual({ at: 0, level: 'INFO', text: 'x' })
    for (const raw of ['не json', 'null', '[]', '{"text": "x"}', '{"level": "INFO"}']) expect(parseLogLine(raw)).toBeNull()
  })

  it('подключается к /api/v1/logs с токеном, отдаёт строки и переподключается', () => {
    const handlers = { onLine: vi.fn(), onOpen: vi.fn(), onClose: vi.fn() }
    const conn = connectLogs('t k', handlers, { WebSocketImpl: FakeWS as unknown as typeof WebSocket })
    const ws = FakeWS.all[0]
    if (!ws) throw new Error('нет сокета')
    expect(ws.url).toBe(`ws://${location.host}/api/v1/logs?token=t%20k`)
    ws.onopen?.()
    ws.onmessage?.({ data: '{"at": 1, "level": "INFO", "text": "привет"}' })
    ws.onmessage?.({ data: 'мусор' })
    expect(handlers.onOpen).toHaveBeenCalledTimes(1)
    expect(handlers.onLine).toHaveBeenCalledTimes(1)
    ws.onclose?.({ code: 1006 })
    vi.advanceTimersByTime(1000)
    expect(FakeWS.all).toHaveLength(2)
    conn.close()
  })
})
