// Загрузка ресурсов ядра в состояние. Ошибка загрузки оставляет прежние данные.
import type { Client } from './actions'
import type { Loaded } from './model'
import { MAX_TURNS } from './model'
import type { Dispatch, Outcome, Reply } from './request'
import { send } from './request'

export type Resource = Loaded['resource']

export const ALL_RESOURCES: Resource[] = ['status', 'config', 'voices', 'models', 'turns']
/** Что перечитать после change_applied и voice_ready. */
export const AFTER_CHANGE: Resource[] = ['config', 'status', 'voices']
/** Ollama недоступна — /models отвечает этим кодом. */
const OLLAMA_DOWN = 502

function pick<T>(outcome: Outcome<T>): T | null {
  return outcome.ok ? outcome.data : null
}

async function fetchResource(client: Client, dispatch: Dispatch, resource: Resource): Promise<Loaded | null> {
  const get = <T>(run: () => Promise<Reply<T>>) => send(dispatch, run)
  switch (resource) {
    case 'status': {
      const data = pick(await get(() => client.GET('/api/v1/status')))
      return data && { resource, data }
    }
    case 'config': {
      const data = pick(await get(() => client.GET('/api/v1/config')))
      return data && { resource, data }
    }
    case 'voices': {
      const data = pick(await get(() => client.GET('/api/v1/voices')))
      return data && { resource, data }
    }
    case 'models': {
      const outcome = await get(() => client.GET('/api/v1/models'))
      if (outcome.ok) return { resource, data: outcome.data }
      return outcome.status === OLLAMA_DOWN ? { resource, data: [] } : null
    }
    case 'turns': {
      const query = { limit: MAX_TURNS }
      const data = pick(await get(() => client.GET('/api/v1/turns', { params: { query } })))
      return data && { resource, data }
    }
  }
}

/** Загружает ресурсы параллельно; каждый готовый сразу попадает в состояние. */
export async function loadResources(client: Client, dispatch: Dispatch, resources: Resource[]): Promise<void> {
  await Promise.all(
    resources.map(async (resource) => {
      const loaded = await fetchResource(client, dispatch, resource)
      if (loaded) dispatch({ type: 'loaded', ...loaded })
    }),
  )
}
