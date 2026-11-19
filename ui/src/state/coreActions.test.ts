import { describe, expect, it, vi } from 'vitest'
import type { Client } from './actions'
import { createCoreActions } from './coreActions'
import type { Action } from './model'
import { makeState, makeStatus } from '../components/fixtures'
import { reduce } from './reducer'

function setup() {
  const client = { GET: vi.fn(), POST: vi.fn() }
  const dispatched: Action[] = []
  const actions = createCoreActions(client as unknown as Client, (a) => dispatched.push(a), 'tok')
  return { client, dispatched, actions }
}

const info = { version: '1.0', uptime_s: 5, state: 'ready', port: 8765, data_dir: '/d' }

describe('действия вкладки «Ядро»', () => {
  it('loadCoreInfo: сведения или null без уведомления', async () => {
    const { client, actions, dispatched } = setup()
    client.GET.mockResolvedValueOnce({ data: info, response: { status: 200 } })
    expect(await actions.loadCoreInfo()).toEqual(info)
    expect(client.GET).toHaveBeenCalledWith('/api/v1/core')
    client.GET.mockRejectedValueOnce(new Error('нет сети'))
    expect(await actions.loadCoreInfo()).toBeNull()
    expect(dispatched).toEqual([])
  })

  it('stopCore: POST /core/stop; отказ — уведомление и false', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValueOnce({ data: null, response: { status: 202 } })
    expect(await actions.stopCore()).toBe(true)
    expect(client.POST).toHaveBeenCalledWith('/api/v1/core/stop')
    client.POST.mockResolvedValueOnce({ error: { detail: 'нет' }, response: { status: 500 } })
    expect(await actions.stopCore()).toBe(false)
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: 'нет', tone: 'error' } }])
  })

  it('unloadModel: имя в теле; удалось — модель убрана и уведомление', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValueOnce({ data: null, response: { status: 204 } })
    await actions.unloadModel('hf.co/a/b:Q4')
    expect(client.POST).toHaveBeenCalledWith('/api/v1/models/unload', { body: { name: 'hf.co/a/b:Q4' } })
    expect(dispatched).toEqual([
      { type: 'modelUnloaded', name: 'hf.co/a/b:Q4' },
      { type: 'notice', notice: { text: 'Модель hf.co/a/b:Q4 выгружена', tone: 'ok' } },
    ])
  })

  it('unloadModel: модели нет в памяти — только уведомление', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValueOnce({ error: { detail: 'Модель не загружена' }, response: { status: 404 } })
    await actions.unloadModel('x')
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: 'Модель не загружена', tone: 'error' } }])
  })

  it('редьюсер: modelUnloaded убирает модель из status', () => {
    const state = makeState({ status: makeStatus({ ollama: { reachable: true, loaded: ['a', 'b'] } }) })
    expect(reduce(state, { type: 'modelUnloaded', name: 'a' }).status?.ollama.loaded).toEqual(['b'])
    const empty = makeState({ status: null })
    expect(reduce(empty, { type: 'modelUnloaded', name: 'a' })).toBe(empty)
  })
})
