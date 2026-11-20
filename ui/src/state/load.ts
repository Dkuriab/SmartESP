// Загрузка ресурсов ядра в состояние. Ошибка загрузки оставляет прежние данные.
import type { Client } from './actions'
import type { Loaded } from './model'
import { MAX_TURNS } from './model'
import type { Dispatch, Outcome, Reply } from './request'
import { send } from './request'

export type Resource = Loaded['resource']

export const ALL_RESOURCES: Resource[] = ['status', 'config', 'voices', 'models', 'turns', 'connectors', 'tasks']
/** Что перечитать после change_applied и voice_ready. */
export const AFTER_CHANGE: Resource[] = ['config', 'status', 'voices', 'connectors']
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
    case 'connectors': {
      const data = pick(await get(() => client.GET('/api/v1/connectors')))
      return data && { resource, data }
    }
    case 'tasks': {
      const data = pick(await get(() => client.GET('/api/v1/tasks')))
      return data && { resource, data }
    }
    case 'turns': {
      const query = { limit: MAX_TURNS }
      const data = pick(await get(() => client.GET('/api/v1/turns', { params: { query } })))
      return data && { resource, data }
    }
  }
}

export type Loader = (resources: Resource[]) => void

/**
 * Загрузчик: ресурсы грузятся параллельно, каждый готовый сразу попадает
 * в состояние (с временем запроса). Если ресурс уже грузится, второй запрос
 * не начинается — по окончании текущего ресурс перечитывается один раз.
 */
export function createLoader(client: Client, dispatch: Dispatch, now: () => number = Date.now): Loader {
  const running = new Set<Resource>()
  const again = new Set<Resource>()

  async function run(resource: Resource) {
    running.add(resource)
    do {
      again.delete(resource)
      const requestedAt = now()
      const loaded = await fetchResource(client, dispatch, resource)
      if (loaded) dispatch({ type: 'loaded', requestedAt, ...loaded })
    } while (again.has(resource))
    running.delete(resource)
  }

  return (resources) => {
    for (const resource of resources) {
      if (running.has(resource)) again.add(resource)
      else void run(resource)
    }
  }
}
