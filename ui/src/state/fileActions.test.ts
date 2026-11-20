import { describe, expect, it, vi } from 'vitest'
import type { Client } from './actions'
import { createFileActions, MAX_FILE_BYTES, NOT_PLAYING, TOO_BIG } from './fileActions'
import type { Action } from './model'

function setup() {
  const client = { POST: vi.fn(), DELETE: vi.fn() }
  const dispatched: Action[] = []
  const actions = createFileActions(client as unknown as Client, (a) => dispatched.push(a))
  return { client, dispatched, actions }
}

const PATH = '/api/v1/devices/{device_id}/play'
const params = { path: { device_id: 'aa:bb' } }

describe('действия с файлом на колонке', () => {
  it('playFile шлёт файл в multipart и ждёт событий', async () => {
    const { client, dispatched, actions } = setup()
    client.POST.mockResolvedValue({ data: { status: 'started' }, response: { status: 202 } })
    const file = new File(['ID3'], 'song.mp3', { type: 'audio/mpeg' })
    await actions.playFile('aa:bb', file)
    const [path, options] = client.POST.mock.calls[0] as [string, { params: unknown; bodySerializer: () => FormData }]
    expect(path).toBe(PATH)
    expect(options.params).toEqual(params)
    expect(options.bodySerializer().get('audio')).toBe(file)
    expect(dispatched).toEqual([
      { type: 'filePhase', deviceId: 'aa:bb', phase: 'sending' },
      { type: 'filePhase', deviceId: 'aa:bb', phase: 'playing', onlyFrom: 'sending' },
    ])
  })

  it('playFile: отказ ядра — уведомление с его текстом и фаза снята', async () => {
    const { client, dispatched, actions } = setup()
    client.POST.mockResolvedValue({ error: { detail: 'Колонка занята' }, response: { status: 409 } })
    await actions.playFile('aa:bb', new File(['x'], 'a.wav'))
    expect(dispatched.slice(1)).toEqual([
      { type: 'notice', notice: { text: 'Колонка занята', tone: 'error' } },
      { type: 'filePhase', deviceId: 'aa:bb', phase: null },
    ])
  })

  it('playFile: файл больше 50 МБ не отправляется, уведомление', async () => {
    const { client, dispatched, actions } = setup()
    const big = new File(['x'], 'big.wav')
    Object.defineProperty(big, 'size', { value: MAX_FILE_BYTES + 1 })
    await actions.playFile('aa:bb', big)
    expect(client.POST).not.toHaveBeenCalled()
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: TOO_BIG, tone: 'error' } }])
  })

  it('stopFile: остановлен — фаза снята (итог придёт событием)', async () => {
    const { client, dispatched, actions } = setup()
    client.DELETE.mockResolvedValue({ data: { stopped: true }, response: { status: 200 } })
    await actions.stopFile('aa:bb')
    expect(client.DELETE).toHaveBeenCalledWith(PATH, { params })
    expect(dispatched).toEqual([{ type: 'filePhase', deviceId: 'aa:bb', phase: null }])
  })

  it('stopFile: файл не играл — уведомление', async () => {
    const { client, dispatched, actions } = setup()
    client.DELETE.mockResolvedValue({ data: { stopped: false }, response: { status: 200 } })
    await actions.stopFile('aa:bb')
    expect(dispatched[0]).toEqual({ type: 'notice', notice: { text: NOT_PLAYING, tone: 'ok' } })
  })

  it('stopFile: ошибка — только уведомление', async () => {
    const { client, dispatched, actions } = setup()
    client.DELETE.mockResolvedValue({ error: { detail: 'Колонка не найдена' }, response: { status: 404 } })
    await actions.stopFile('aa:bb')
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: 'Колонка не найдена', tone: 'error' } }])
  })
})
