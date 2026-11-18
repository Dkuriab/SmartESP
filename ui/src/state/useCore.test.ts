import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EventHandlers } from '../api/events'
import { useCore } from './useCore'

const sockets: EventHandlers[] = []
const closeSocket = vi.fn()
const GET = vi.fn()

vi.mock('../api/events', () => ({
  connectEvents: (_token: string, handlers: EventHandlers) => {
    sockets.push(handlers)
    return { close: closeSocket }
  },
}))
vi.mock('../api/client', () => ({ createClient: () => ({ GET, POST: vi.fn(), PATCH: vi.fn() }) }))

function socket(): EventHandlers {
  const last = sockets.at(-1)
  if (!last) throw new Error('нет подключения')
  return last
}

function paths(): string[] {
  return GET.mock.calls.map((c) => String(c[0]))
}

/** Хранилище в памяти: встроенное в окружение тестов ненадёжно. */
function memoryStorage(): Storage {
  const data = new Map<string, string>()
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size
    },
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
  sockets.length = 0
  GET.mockReset()
  GET.mockResolvedValue({ data: [], response: { status: 200 } })
  localStorage.setItem('smartesp.token', 'tok')
})
afterEach(() => vi.unstubAllGlobals())

describe('useCore', () => {
  it('без токена — unauthorized и без подключения', () => {
    localStorage.clear()
    const { result } = renderHook(() => useCore())
    expect(result.current[0].connection).toBe('unauthorized')
    expect(sockets).toHaveLength(0)
  })

  it('при подключении — online и загрузка всех ресурсов', async () => {
    const { result } = renderHook(() => useCore())
    expect(result.current[0].connection).toBe('connecting')
    act(() => socket().onOpen())
    expect(result.current[0].connection).toBe('online')
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(5))
    expect(paths().sort()).toEqual(
      ['/api/v1/config', '/api/v1/models', '/api/v1/status', '/api/v1/turns', '/api/v1/voices'],
    )
  })

  it('обрыв — offline с данными, переподключение — всё заново', async () => {
    const { result } = renderHook(() => useCore())
    act(() => socket().onEvent({ kind: 'turn_finished', data: { turn_id: 1 }, at: 1 }))
    act(() => socket().onClose(1006))
    expect(result.current[0].connection).toBe('offline')
    expect(result.current[0].turns).toHaveLength(1)
    act(() => socket().onOpen())
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(5))
  })

  it('change_applied — перечитывает config, status, voices', async () => {
    renderHook(() => useCore())
    act(() => socket().onEvent({ kind: 'change_applied', data: { change_id: 1, ok: true }, at: 1 }))
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(3))
    expect(paths().sort()).toEqual(['/api/v1/config', '/api/v1/status', '/api/v1/voices'])
  })

  it('4401 — unauthorized; setToken подключается заново', () => {
    const { result } = renderHook(() => useCore())
    act(() => socket().onClose(4401))
    expect(result.current[0].connection).toBe('unauthorized')
    act(() => result.current[1].setToken('new'))
    expect(result.current[0].connection).toBe('connecting')
    expect(closeSocket).toHaveBeenCalled()
    expect(sockets).toHaveLength(2)
    expect(localStorage.getItem('smartesp.token')).toBe('new')
  })
})
