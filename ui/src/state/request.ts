// Общая обработка ответов API: 401, ошибки с текстом, обрыв сети.
import type { Action } from './model'

/** Ответ openapi-fetch в той мере, в какой он нужен здесь. */
export type Reply<T> = { data?: T; error?: unknown; response: { status: number } }

export type Dispatch = (action: Action) => void

export const OFFLINE_TEXT = 'Нет связи с ядром'

/** Текст ошибки из тела ответа: ChangeOut.error или ErrorOut.detail. */
export function errorText(error: unknown, status: number): string {
  if (error && typeof error === 'object') {
    const body = error as { error?: unknown; detail?: unknown }
    if (typeof body.error === 'string' && body.error) return body.error
    if (typeof body.detail === 'string' && body.detail) return body.detail
  }
  return `Ошибка ядра (${status})`
}

/** Итог запроса; status у неудачи — HTTP-код, null — сеть недоступна. */
export type Outcome<T> = { ok: true; data: T } | { ok: false; text: string; status: number | null }

/**
 * Выполняет запрос и разбирает ответ без исключений.
 * 401 переводит связь в «unauthorized»; остальные ошибки возвращаются текстом.
 */
export async function send<T>(dispatch: Dispatch, run: () => Promise<Reply<T>>): Promise<Outcome<T>> {
  let reply: Reply<T>
  try {
    reply = await run()
  } catch {
    return { ok: false, text: OFFLINE_TEXT, status: null }
  }
  const status = reply.response.status
  if (status === 401) {
    dispatch({ type: 'connection', connection: 'unauthorized' })
    return { ok: false, text: '', status }
  }
  if (reply.error !== undefined || status >= 400) return { ok: false, text: errorText(reply.error, status), status }
  return { ok: true, data: reply.data as T }
}

/** Как send, но ошибку (кроме 401) показывает уведомлением. */
export async function sendNotify<T>(dispatch: Dispatch, run: () => Promise<Reply<T>>): Promise<Outcome<T>> {
  const outcome = await send(dispatch, run)
  if (!outcome.ok && outcome.text) dispatch({ type: 'notice', notice: { text: outcome.text, tone: 'error' } })
  return outcome
}
