import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LogHandlers } from '../api/logs'
import { appendLines, FLUSH_MS, isProblem, useLogLines } from './logs'

const line = (id: number, level = 'INFO') => ({ id, at: id, level, text: `строка ${id}` })

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('журнал в интерфейсе', () => {
  it('appendLines держит последние max строк', () => {
    const prev = [line(1), line(2)]
    expect(appendLines(prev, [])).toBe(prev)
    expect(appendLines(prev, [line(3), line(4)], 3).map((l) => l.id)).toEqual([2, 3, 4])
  })

  it('«Ошибки» — предупреждения и ошибки', () => {
    expect(['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((level) => isProblem(line(0, level)))).toEqual([
      false,
      false,
      true,
      true,
      true,
    ])
  })

  it('useLogLines: пачки строк, сброс при переподключении, отписка', () => {
    let handlers: LogHandlers | undefined
    const stop = vi.fn()
    const watch = vi.fn((h: LogHandlers) => {
      handlers = h
      return stop
    })
    const { result, unmount } = renderHook(() => useLogLines(watch))
    act(() => handlers?.onOpen())
    expect(result.current.online).toBe(true)
    act(() => {
      handlers?.onLine({ at: 1, level: 'INFO', text: 'a' })
      handlers?.onLine({ at: 2, level: 'ERROR', text: 'b' })
    })
    expect(result.current.lines).toEqual([])
    act(() => vi.advanceTimersByTime(FLUSH_MS))
    expect(result.current.lines.map((l) => l.text)).toEqual(['a', 'b'])
    act(() => {
      handlers?.onClose(1006)
      handlers?.onOpen()
    })
    expect(result.current.lines).toEqual([])
    unmount()
    expect(stop).toHaveBeenCalled()
  })
})
