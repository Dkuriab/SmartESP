import { describe, expect, it } from 'vitest'
import type { CoreEvent } from '../api/events'
import { makeState, makeStatus } from '../components/fixtures'
import type { CoreState } from './model'
import { reduce } from './reducer'

function event(kind: string, data: Record<string, unknown>): CoreEvent {
  return { kind, data, at: 1 }
}

const devices = [{ device_id: 'aa', name: 'Кухня', connected: true, remote: '', fw: '', protocol: 3, volume: 50 }]

function state(files: CoreState['files'] = {}): CoreState {
  return makeState({ status: makeStatus({ devices }), files })
}

describe('файл на колонке', () => {
  it('filePhase ставит и снимает фазу', () => {
    const sending = reduce(state(), { type: 'filePhase', deviceId: 'aa', phase: 'sending' })
    expect(sending.files).toEqual({ aa: 'sending' })
    expect(reduce(sending, { type: 'filePhase', deviceId: 'aa', phase: null }).files).toEqual({})
  })

  it('onlyFrom: ответ ядра не возвращает «играет» после итога', () => {
    const done = state()
    const after = reduce(done, { type: 'filePhase', deviceId: 'aa', phase: 'playing', onlyFrom: 'sending' })
    expect(after).toBe(done)
    const sending = state({ aa: 'sending' })
    expect(reduce(sending, { type: 'filePhase', deviceId: 'aa', phase: 'playing', onlyFrom: 'sending' }).files).toEqual({
      aa: 'playing',
    })
  })

  it('playback_started — играет', () => {
    const next = reduce(state({ aa: 'sending' }), { type: 'event', event: event('playback_started', { device_id: 'aa' }) })
    expect(next.files).toEqual({ aa: 'playing' })
  })

  it.each([
    ['delivered', 'Файл доигран на колонке «Кухня»', 'ok'],
    ['interrupted', 'Файл на колонке «Кухня» остановлен', 'ok'],
    ['busy', 'Колонка «Кухня» была занята — файл не проигран', 'error'],
    ['lost', 'Колонка «Кухня» не доиграла файл: нет связи', 'error'],
  ])('playback_finished %s — уведомление и фаза снята', (delivery, text, tone) => {
    const finished = event('playback_finished', { device_id: 'aa', delivery })
    const next = reduce(state({ aa: 'playing' }), { type: 'event', event: finished })
    expect(next.files).toEqual({})
    expect(next.notice).toEqual({ text, tone })
  })

  it('неизвестная колонка в уведомлении — по id; без device_id событие не меняет состояние', () => {
    const finished = event('playback_finished', { device_id: 'zz', delivery: 'delivered' })
    expect(reduce(state(), { type: 'event', event: finished }).notice?.text).toBe('Файл доигран на колонке «zz»')
    const before = state({ aa: 'playing' })
    expect(reduce(before, { type: 'event', event: event('playback_finished', {}) })).toBe(before)
  })

  it('переподключение сбрасывает фазы', () => {
    expect(reduce(state({ aa: 'playing' }), { type: 'opened' }).files).toEqual({})
  })
})
