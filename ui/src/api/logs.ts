// Журнал ядра: WebSocket /api/v1/logs — сначала последние строки, затем новые.
import type { SocketOptions } from './socket'
import { connectSocket } from './socket'

/** Строка журнала: время (секунды Unix), уровень (INFO, WARNING…) и текст целиком. */
export type LogLine = { at: number; level: string; text: string }

export type LogHandlers = {
  onLine(line: LogLine): void
  /** (Пере)подключение: ядро пришлёт последние строки заново. */
  onOpen(): void
  onClose(code: number): void
}

/** Строка из сообщения: объект с текстом и уровнем строкой; иначе null. */
export function parseLogLine(text: string): LogLine | null {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return null
  }
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return null
  const { at, level, text: body } = raw as Record<string, unknown>
  if (typeof body !== 'string' || typeof level !== 'string') return null
  return { at: typeof at === 'number' ? at : 0, level, text: body }
}

/** Подключается к журналу и сам переподключается; close() останавливает всё. */
export function connectLogs(token: string, handlers: LogHandlers, opts: SocketOptions = {}): { close(): void } {
  return connectSocket(
    '/api/v1/logs',
    token,
    {
      onMessage(text) {
        const line = parseLogLine(text)
        if (line) handlers.onLine(line)
      },
      onOpen: handlers.onOpen,
      onClose: handlers.onClose,
    },
    opts,
  )
}
