// Лента событий ядра: WebSocket с автоматическим переподключением.

export type CoreEvent = {
  kind: string
  data: Record<string, unknown>
  at: number
}

export type EventHandlers = {
  onEvent(e: CoreEvent): void
  onOpen(): void
  onClose(code: number): void
}

export type EventOptions = {
  /** Задержки переподключения, мс; последняя повторяется. */
  delays?: number[]
  WebSocketImpl?: typeof WebSocket
}

const DEFAULT_DELAYS = [1000, 2000, 5000]
/** Ядро закрывает соединение с этим кодом при неверном токене. */
const AUTH_FAILED = 4401

function eventsUrl(token: string): string {
  const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${scheme}//${location.host}/api/v1/events?token=${encodeURIComponent(token)}`
}

/**
 * Подключается к /api/v1/events и сам переподключается по задержкам.
 * Код 4401 — без переподключения. close() останавливает всё.
 */
export function connectEvents(
  token: string,
  handlers: EventHandlers,
  opts: EventOptions = {},
): { close(): void } {
  const delays = opts.delays ?? DEFAULT_DELAYS
  const Impl = opts.WebSocketImpl ?? WebSocket
  let stopped = false
  let attempt = 0
  let socket: WebSocket | null = null
  let timer: ReturnType<typeof setTimeout> | undefined

  function connect() {
    const ws = new Impl(eventsUrl(token))
    socket = ws
    ws.onopen = () => {
      attempt = 0
      handlers.onOpen()
    }
    ws.onmessage = (m) => {
      try {
        handlers.onEvent(JSON.parse(String(m.data)) as CoreEvent)
      } catch {
        // битое сообщение пропускаем
      }
    }
    ws.onclose = (e) => {
      if (stopped) return
      handlers.onClose(e.code)
      if (e.code === AUTH_FAILED) return
      const delay = delays[Math.min(attempt, delays.length - 1)]
      attempt += 1
      timer = setTimeout(connect, delay)
    }
  }

  connect()
  return {
    close() {
      stopped = true
      clearTimeout(timer)
      socket?.close()
    },
  }
}
