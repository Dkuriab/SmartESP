import { describe, expect, it, vi } from 'vitest'
import type { Client } from './actions'
import { createActions } from './actions'
import type { Action, Config } from './model'

type Reply = { data?: unknown; error?: unknown; response: { status: number } }

function ok(data: unknown, status = 200): Reply {
  return { data, response: { status } }
}

function fail(error: unknown, status: number): Reply {
  return { error, response: { status } }
}

function config(): Config {
  return {
    effective: {
      executors: [
        { id: 'dispatcher', name: 'Диспетчер', model: 'a', entry: true, system_prompt: 'p' },
        { id: 'coder', name: 'Код', model: 'b', entry: false, system_prompt: '' },
      ],
    },
    overridden: [],
    restart_sections: [],
    dispatcher_prompt: 'p',
    executor_prompts: {},
  }
}

function setup(current: Config | null = null) {
  const client = { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }
  const dispatched: Action[] = []
  const onToken = vi.fn()
  const actions = createActions({
    client: client as unknown as Client,
    dispatch: (a) => dispatched.push(a),
    getConfig: () => current,
    onToken,
    now: () => 42,
  })
  return { client, dispatched, actions, onToken }
}

const accepted = { change_id: 3, status: 'accepted', error: '' }

describe('actions', () => {
  it('select, selectTurn и dismissNotice отправляют действия редьюсера', () => {
    const { actions, dispatched } = setup()
    actions.select({ kind: 'device', id: 'a' })
    actions.selectTurn(5)
    actions.dismissNotice()
    actions.showNotice({ text: 'Ой', tone: 'error' })
    expect(dispatched).toEqual([
      { type: 'select', selected: { kind: 'device', id: 'a' } },
      { type: 'selectTurn', turnId: 5 },
      { type: 'dismissNotice' },
      { type: 'notice', notice: { text: 'Ой', tone: 'error' } },
    ])
  })

  it('setDispatcher шлёт executors целиком, меняя модель только у входного', async () => {
    const { client, actions, dispatched } = setup(config())
    client.PATCH.mockResolvedValue(ok(accepted))
    await actions.setDispatcher({ model: 'x' })
    expect(client.PATCH).toHaveBeenCalledWith('/api/v1/config', {
      body: {
        executors: [
          { id: 'dispatcher', name: 'Диспетчер', model: 'x', entry: true, system_prompt: 'p' },
          { id: 'coder', name: 'Код', model: 'b', entry: false, system_prompt: '' },
        ],
      },
    })
    expect(dispatched).toContainEqual({ type: 'changeSent', changeId: 3, description: expect.any(String), at: 42 })
  })

  it('setDispatcher: поле undefined не затирает текущее значение', async () => {
    const { client, actions } = setup(config())
    client.PATCH.mockResolvedValue(ok(accepted))
    await actions.setDispatcher({ model: 'x', system_prompt: undefined })
    const body = (client.PATCH.mock.calls[0]?.[1] as { body: { executors: unknown[] } }).body
    expect(body.executors[0]).toMatchObject({ model: 'x', system_prompt: 'p' })
  })

  it('setDispatcher без загруженных настроек — notice, без запроса', async () => {
    const { client, actions, dispatched } = setup()
    await actions.setDispatcher({ system_prompt: 'новый' })
    expect(client.PATCH).not.toHaveBeenCalled()
    expect(dispatched[0]).toMatchObject({ type: 'notice', notice: { tone: 'error' } })
  })

  it('422 → notice error с текстом, без исключения', async () => {
    const { client, actions, dispatched } = setup()
    client.PATCH.mockResolvedValue(fail({ change_id: 4, status: 'invalid', error: 'нет такого tts' }, 422))
    await expect(actions.selectVoice('x', 'y')).resolves.toBeUndefined()
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: 'нет такого tts', tone: 'error' } }])
  })

  it('503 при скачивании голоса → notice error', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValue(fail({ change_id: 5, status: 'stopping', error: 'ядро останавливается' }, 503))
    await actions.downloadVoice('vosk', 'big')
    expect(client.POST).toHaveBeenCalledWith('/api/v1/voices/download', { body: { kind: 'vosk', voice: 'big' } })
    expect(dispatched).toEqual([
      { type: 'downloadRequested', kind: 'vosk', voice: 'big' },
      { type: 'notice', notice: { text: 'ядро останавливается', tone: 'error' } },
    ])
  })

  it('401 → connection unauthorized', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValue(fail({ detail: 'Неверный токен' }, 401))
    await actions.restart()
    expect(dispatched).toEqual([
      { type: 'restarting', on: true },
      { type: 'connection', connection: 'unauthorized' },
      { type: 'restarting', on: false },
    ])
  })

  it('restart: принят — кнопка ждёт переподключения', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValue(ok(null, 202))
    await actions.restart()
    expect(dispatched).toEqual([{ type: 'restarting', on: true }])
  })

  it('сеть недоступна → notice, без исключения', async () => {
    const { client, actions, dispatched } = setup()
    client.PATCH.mockRejectedValue(new TypeError('Failed to fetch'))
    await actions.renameDevice('aa:bb', 'Кухня')
    expect(dispatched[0]).toMatchObject({ type: 'notice', notice: { tone: 'error' } })
  })

  it('renameDevice, setStages и selectVoice шлют нужные правки', async () => {
    const { client, actions } = setup()
    client.PATCH.mockResolvedValue(ok(accepted))
    await actions.renameDevice('aa:bb', 'Кухня')
    await actions.setStages([{ kind: 'whisper_detect', timeout_ms: 300 }])
    await actions.selectVoice('silero', 'xenia')
    const bodies = client.PATCH.mock.calls.map((c) => (c[1] as { body: unknown }).body)
    expect(bodies).toEqual([
      { devices: { 'aa:bb': { name: 'Кухня' } } },
      { stages: [{ kind: 'whisper_detect', timeout_ms: 300 }] },
      { tts: { kind: 'silero', voice: 'xenia' } },
    ])
  })

  it('previewVoice отдаёт Blob', async () => {
    const { client, actions } = setup()
    const blob = new Blob(['wav'])
    client.POST.mockResolvedValue(ok(blob))
    await expect(actions.previewVoice('silero', 'xenia', 'whisper')).resolves.toBe(blob)
    expect(client.POST).toHaveBeenCalledWith('/api/v1/voices/preview', {
      body: { kind: 'silero', voice: 'xenia', style: 'whisper' },
      parseAs: 'blob',
    })
  })

  it('previewVoice при 409 — notice и отказ', async () => {
    const { client, actions, dispatched } = setup()
    client.POST.mockResolvedValue(fail({ detail: 'Голос не скачан' }, 409))
    await expect(actions.previewVoice('silero', 'xenia', 'normal')).rejects.toThrow('Голос не скачан')
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: 'Голос не скачан', tone: 'error' } }])
  })

  it('loadAccess отдаёт адреса, при ошибке — []', async () => {
    const { client, actions } = setup()
    client.GET.mockResolvedValueOnce(ok({ urls: ['http://10.0.0.2:8765/?token=t'] }))
    await expect(actions.loadAccess()).resolves.toEqual(['http://10.0.0.2:8765/?token=t'])
    client.GET.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(actions.loadAccess()).resolves.toEqual([])
  })

  it('setToken передаёт токен дальше', () => {
    const { actions, onToken } = setup()
    actions.setToken('abc')
    expect(onToken).toHaveBeenCalledWith('abc')
  })
})
