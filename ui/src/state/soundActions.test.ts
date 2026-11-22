import { describe, expect, it, vi } from 'vitest'
import type { Client } from './actions'
import type { Action } from './model'
import { createSoundActions, MAX_SOUND_BYTES, SOUND_TOO_BIG } from './soundActions'

function setup() {
  const client = { GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }
  const dispatched: Action[] = []
  const actions = createSoundActions(client as unknown as Client, (a) => dispatched.push(a))
  return { client, dispatched, actions }
}

const sound = { sha256: 'a'.repeat(64), name: 'x.wav', duration_s: 3 }

describe('действия со звуками колонок', () => {
  it('uploadSound: multipart, колонка — в query; обрезанный звук — уведомление', async () => {
    const { client, dispatched, actions } = setup()
    client.POST.mockResolvedValue({ data: { sound, trimmed: true }, response: { status: 200 } })
    const file = new File(['RIFF'], 'x.wav')
    expect(await actions.uploadSound('wake', file, 'aa:bb')).toBe(true)
    const [path, options] = client.POST.mock.calls[0] as [string, { params: unknown; bodySerializer: () => FormData }]
    expect(path).toBe('/api/v1/sounds/{tone}')
    expect(options.params).toEqual({ path: { tone: 'wake' }, query: { device_id: 'aa:bb' } })
    expect(options.bodySerializer().get('file')).toBe(file)
    expect(dispatched).toEqual([{ type: 'notice', notice: { text: 'Звук длиннее 3 с — обрезан', tone: 'ok' } }])
  })

  it('uploadSound: большой файл не уходит; отказ ядра — уведомление', async () => {
    const { client, dispatched, actions } = setup()
    const big = new File([new Uint8Array(MAX_SOUND_BYTES + 1)], 'big.wav')
    expect(await actions.uploadSound('wake', big, null)).toBe(false)
    expect(client.POST).not.toHaveBeenCalled()
    expect(dispatched[0]).toEqual({ type: 'notice', notice: { text: SOUND_TOO_BIG, tone: 'error' } })
    client.POST.mockResolvedValue({ error: { detail: 'В файле нет звука' }, response: { status: 422 } })
    expect(await actions.uploadSound('error', new File(['x'], 'a.wav'), null)).toBe(false)
    expect(dispatched[1]).toEqual({ type: 'notice', notice: { text: 'В файле нет звука', tone: 'error' } })
  })

  it('resetSound для всех — без device_id; loadSounds без связи — null', async () => {
    const { client, actions } = setup()
    client.DELETE.mockResolvedValue({ response: { status: 204 } })
    expect(await actions.resetSound('listen', null)).toBe(true)
    expect(client.DELETE).toHaveBeenCalledWith('/api/v1/sounds/{tone}', { params: { path: { tone: 'listen' }, query: {} } })
    client.GET.mockRejectedValue(new Error('offline'))
    expect(await actions.loadSounds()).toBeNull()
  })
})
