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

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** Событие из сообщения: только объект со строковым kind; иначе null. */
export function parseEvent(text: string): CoreEvent | null {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return null
  }
  if (!isObject(raw) || typeof raw.kind !== 'string') return null
  const data = isObject(raw.data) ? raw.data : {}
  return { kind: raw.kind, data, at: typeof raw.at === 'number' ? raw.at : 0 }
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
      const event = parseEvent(String(m.data))
      if (event) handlers.onEvent(event) // битое сообщение пропускаем
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
