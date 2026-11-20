import { describe, expect, it, vi } from 'vitest'
import type { Client } from './actions'
import { createLoader } from './load'
import type { Action } from './model'

type Reply = { data?: unknown; error?: unknown; response: { status: number } }

function setup() {
  const resolvers: Array<(r: Reply) => void> = []
  const GET = vi.fn(() => new Promise<Reply>((resolve) => resolvers.push(resolve)))
  const dispatched: Action[] = []
  let clock = 0
  const load = createLoader({ GET } as unknown as Client, (a) => dispatched.push(a), () => ++clock)
  return { GET, dispatched, load, resolvers }
}

async function flush() {
  await new Promise((r) => setTimeout(r, 0))
}

describe('createLoader', () => {
  it('ресурс уже грузится — второй запрос после первого, один раз', async () => {
    const { GET, dispatched, load, resolvers } = setup()
    load(['status'])
    load(['status'])
    load(['status'])
    expect(GET).toHaveBeenCalledTimes(1)
    resolvers[0]?.({ data: { applying: false }, response: { status: 200 } })
    await flush()
    expect(GET).toHaveBeenCalledTimes(2)
    resolvers[1]?.({ data: { applying: true }, response: { status: 200 } })
    await flush()
    expect(GET).toHaveBeenCalledTimes(2)
    expect(dispatched.map((a) => a.type === 'loaded' && a.requestedAt)).toEqual([1, 2])
  })

  it('Ollama недоступна (502) → models: []; другая ошибка — без изменений', async () => {
    const { dispatched, load, resolvers } = setup()
    load(['models'])
    resolvers[0]?.({ error: { detail: 'нет Ollama' }, response: { status: 502 } })
    await flush()
    load(['models'])
    resolvers[1]?.({ error: { detail: 'сбой' }, response: { status: 500 } })
    await flush()
    expect(dispatched).toEqual([{ type: 'loaded', resource: 'models', data: [], requestedAt: 1 }])
  })

  it('коннекторы с настройками — из GET /connectors', async () => {
    const { GET, dispatched, load, resolvers } = setup()
    load(['connectors'])
    expect(GET).toHaveBeenCalledWith('/api/v1/connectors')
    const data = [{ id: 'weather', name: 'Погода', state: 'ready', tools: [], settings: [] }]
    resolvers[0]?.({ data, response: { status: 200 } })
    await flush()
    expect(dispatched).toEqual([{ type: 'loaded', resource: 'connectors', data, requestedAt: 1 }])
  })
})
