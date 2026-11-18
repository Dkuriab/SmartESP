import createClient_ from 'openapi-fetch'
import type { paths } from './schema'

/** Типизированный клиент API ядра; токен уходит в заголовке Bearer. */
export function createClient(token: string) {
  return createClient_<paths>({
    headers: { Authorization: `Bearer ${token}` },
  })
}
