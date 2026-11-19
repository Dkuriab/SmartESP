import { describe, expect, it } from 'vitest'
import type { CoreEvent } from '../api/events'
import type { CoreState } from './model'
import { initialState } from './model'
import { reduce } from './reducer'

const ev = (kind: string, data: Record<string, unknown>): CoreEvent => ({ kind, data, at: 1 })
const apply = (state: CoreState, ...events: CoreEvent[]) =>
  events.reduce((s, event) => reduce(s, { type: 'event', event }), state)
const failed = ev('voice_ready', { kind: 'vosk', voice: 'big', ok: false, error: 'нет сети' })

describe('reduce: скачивания голосов', () => {
  it('opened убирает ход скачивания: перезапуск ядра отменил его без voice_ready', () => {
    let s = apply(initialState(), ev('voice_download', { kind: 'vosk', voice: 'big', done: 5, total: 10 }))
    s = reduce(s, { type: 'opened' })
    expect(s.downloads).toEqual({})
  })

  it('повтор скачивания пользователем снова даёт уведомление о неуспехе', () => {
    let s = apply(initialState(), failed)
    s = reduce(s, { type: 'dismissNotice' })
    s = reduce(s, { type: 'downloadRequested', kind: 'vosk', voice: 'big' })
    expect(s.voiceFailures).toEqual({})
    s = apply(s, failed)
    expect(s.notice).toEqual({ text: expect.stringContaining('нет сети'), tone: 'error' })
  })

  it('повтор одного голоса не трогает отметки других', () => {
    let s = apply(initialState(), failed, ev('voice_ready', { kind: 'piper', voice: 'irina', ok: false }))
    s = reduce(s, { type: 'downloadRequested', kind: 'vosk', voice: 'big' })
    expect(s.voiceFailures).toEqual({ 'piper/irina': true })
  })
})

describe('reduce: перезапуск по кнопке', () => {
  it('restarting держится до следующего opened', () => {
    let s = reduce(initialState('online'), { type: 'restarting', on: true })
    expect(s.restarting).toBe(true)
    s = reduce(s, { type: 'connection', connection: 'offline' })
    expect(s.restarting).toBe(true)
    s = reduce(s, { type: 'opened' })
    expect(s.restarting).toBe(false)
  })
})
