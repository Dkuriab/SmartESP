// Лента событий ядра: WebSocket с автоматическим переподключением.
import type { SocketOptions } from './socket'
import { connectSocket } from './socket'

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

export type EventOptions = SocketOptions

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
export function connectEvents(token: string, handlers: EventHandlers, opts: EventOptions = {}): { close(): void } {
  return connectSocket(
    '/api/v1/events',
    token,
    {
      onMessage(text) {
        const event = parseEvent(text)
        if (event) handlers.onEvent(event) // битое сообщение пропускаем
      },
      onOpen: handlers.onOpen,
      onClose: handlers.onClose,
    },
    opts,
  )
}
