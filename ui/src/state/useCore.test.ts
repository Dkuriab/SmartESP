import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EventHandlers } from '../api/events'
import { useCore } from './useCore'

const sockets: EventHandlers[] = []
const closeSocket = vi.fn()
const GET = vi.fn()
const POST = vi.fn()

vi.mock('../api/events', () => ({
  connectEvents: (_token: string, handlers: EventHandlers) => {
    sockets.push(handlers)
    return { close: closeSocket }
  },
}))
vi.mock('../api/client', () => ({ createClient: () => ({ GET, POST, PATCH: vi.fn() }) }))

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
  POST.mockReset()
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

  it('грузит всё сразу, ещё до подключения событий', async () => {
    const { result } = renderHook(() => useCore())
    expect(result.current[0].connection).toBe('connecting')
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(8))
    expect(paths().sort()).toEqual([
      '/api/v1/config',
      '/api/v1/connectors',
      '/api/v1/models',
      '/api/v1/status',
      '/api/v1/streams',
      '/api/v1/tasks',
      '/api/v1/turns',
      '/api/v1/voices',
    ])
  })

  it('при подключении — online и загрузка всех ресурсов ещё раз', async () => {
    const { result } = renderHook(() => useCore())
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(8))
    act(() => socket().onOpen())
    expect(result.current[0].connection).toBe('online')
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(16))
  })

  it('обрыв — offline с данными, переподключение — всё заново', async () => {
    const { result } = renderHook(() => useCore())
    act(() => socket().onEvent({ kind: 'turn_finished', data: { turn_id: 1 }, at: 1 }))
    act(() => socket().onClose(1006))
    expect(result.current[0].connection).toBe('offline')
    expect(result.current[0].turns).toHaveLength(1)
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(8))
    act(() => socket().onOpen())
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(16))
  })

  it('change_applied — перечитывает config, status, voices, connectors', async () => {
    renderHook(() => useCore())
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(8))
    act(() => socket().onEvent({ kind: 'change_applied', data: { change_id: 1, ok: true }, at: 1 }))
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(12))
    expect(paths().slice(8).sort()).toEqual(['/api/v1/config', '/api/v1/connectors', '/api/v1/status', '/api/v1/voices'])
  })

  it('core_state — перечитывает config, status, voices, connectors', async () => {
    renderHook(() => useCore())
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(8))
    act(() => socket().onEvent({ kind: 'core_state', data: { state: 'ready' }, at: 1 }))
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(12))
    expect(paths().slice(8).sort()).toEqual(['/api/v1/config', '/api/v1/connectors', '/api/v1/status', '/api/v1/voices'])
  })

  it('на связи status перечитывается каждые 5 с (модели в памяти Ollama); без связи — нет', async () => {
    // поддельный только setInterval: ожидание ответов идёт на настоящих таймерах
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const flush = () => act(() => new Promise((r) => setTimeout(r, 0)))
    try {
      const { unmount } = renderHook(() => useCore())
      await flush()
      act(() => socket().onOpen())
      await flush()
      expect(GET).toHaveBeenCalledTimes(16)
      vi.advanceTimersByTime(5_000)
      await flush()
      expect(paths().slice(16)).toEqual(['/api/v1/status'])
      act(() => socket().onClose(1006))
      vi.advanceTimersByTime(30_000)
      expect(GET).toHaveBeenCalledTimes(17)
      act(() => socket().onOpen())
      await flush()
      vi.advanceTimersByTime(5_000)
      await flush()
      expect(GET).toHaveBeenCalledTimes(26)
      unmount()
      vi.advanceTimersByTime(30_000)
      expect(GET).toHaveBeenCalledTimes(26)
    } finally {
      vi.useRealTimers()
    }
  })

  it('скрытая вкладка status не опрашивает', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const flush = () => act(() => new Promise((r) => setTimeout(r, 0)))
    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    try {
      renderHook(() => useCore())
      await flush()
      act(() => socket().onOpen())
      await flush()
      const before = GET.mock.calls.length
      vi.advanceTimersByTime(15_000)
      await flush()
      expect(GET).toHaveBeenCalledTimes(before)
      hidden.mockReturnValue(false)
      vi.advanceTimersByTime(5_000)
      await flush()
      expect(paths().slice(before)).toEqual(['/api/v1/status'])
    } finally {
      hidden.mockRestore()
      vi.useRealTimers()
    }
  })

  it('Ollama снова доступна — список моделей перечитывается', async () => {
    let reachable = false
    GET.mockImplementation((path: string) => {
      const data = path.endsWith('/status') ? { applying: false, ollama: { reachable, loaded: [] } } : []
      return Promise.resolve({ data, response: { status: 200 } })
    })
    const { result } = renderHook(() => useCore())
    await waitFor(() => expect(result.current[0].status).not.toBeNull())
    const models = () => paths().filter((p) => p === '/api/v1/models').length
    expect(models()).toBe(1)
    reachable = true
    act(() => socket().onEvent({ kind: 'core_state', data: { state: 'ready' }, at: 1 }))
    await waitFor(() => expect(models()).toBe(2))
    act(() => socket().onEvent({ kind: 'core_state', data: { state: 'ready' }, at: 2 }))
    await waitFor(() => expect(GET).toHaveBeenCalledTimes(17))
    expect(models()).toBe(2) // доступна и была — не перечитываем
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

  it('ответ старого клиента после смены токена состояние не меняет', async () => {
    let reply: (r: unknown) => void = () => {}
    POST.mockReturnValue(new Promise((resolve) => (reply = resolve)))
    const { result } = renderHook(() => useCore())
    let pending: Promise<void> = Promise.resolve()
    act(() => {
      pending = result.current[1].restart()
    })
    act(() => result.current[1].setToken('new'))
    await act(async () => {
      reply({ error: { detail: 'Неверный токен' }, response: { status: 401 } })
      await pending
    })
    expect(result.current[0].connection).toBe('connecting')
  })
})
