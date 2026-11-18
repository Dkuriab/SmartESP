import { describe, expect, it } from 'vitest'
import type { CoreEvent } from '../api/events'
import type { CoreState, Status, Turn } from './model'
import { initialState } from './model'
import { reduce } from './reducer'

function turn(id: number | string, text = `вопрос ${id}`): Turn {
  return {
    turn_id: id,
    device_id: 'aa:bb',
    device_name: 'Кухня',
    text,
    annotations: [],
    style: 'normal',
    answer: 'ответ',
    status: 'ok',
    stt_ms: 100,
    first_text_ms: null,
    first_audio_ms: null,
  }
}

function status(): Status {
  return {
    version: '1',
    uptime_s: 5,
    state: 'ready',
    ollama: { reachable: true, loaded: [] },
    devices: [
      { device_id: 'aa:bb', name: 'Кухня', connected: false, remote: '', fw: '1.0', last_seen: 1 },
    ],
    voice: { kind: 'silero', voice: 'xenia', state: 'ready', error: null },
    applying: false,
    restart_required: false,
  }
}

function ev(kind: string, data: Record<string, unknown>, at = 100): CoreEvent {
  return { kind, data, at }
}

function withStatus(): CoreState {
  return reduce(initialState(), { type: 'loaded', resource: 'status', data: status() })
}

function apply(state: CoreState, ...events: CoreEvent[]): CoreState {
  return events.reduce((s, event) => reduce(s, { type: 'event', event }), state)
}

describe('reduce: turn_finished', () => {
  it('кладёт ход в начало ленты без дублей', () => {
    let s = apply(initialState(), ev('turn_finished', { ...turn(1) }))
    s = apply(s, ev('turn_finished', { ...turn(2) }), ev('turn_finished', { ...turn(2) }))
    expect(s.turns.map((t) => t.turn_id)).toEqual([2, 1])
  })

  it('105 ходов → 100, новые первыми', () => {
    let s = initialState()
    for (let i = 1; i <= 105; i++) s = apply(s, ev('turn_finished', { ...turn(i) }))
    expect(s.turns).toHaveLength(100)
    expect(s.turns[0]?.turn_id).toBe(105)
    expect(s.turns[99]?.turn_id).toBe(6)
  })

  it('ход до загрузки ленты, потом loaded turns с тем же ходом → один элемент', () => {
    let s = apply(initialState(), ev('turn_finished', { ...turn(3) }))
    s = reduce(s, { type: 'loaded', resource: 'turns', data: [turn(3), turn(2), turn(1)] })
    expect(s.turns.map((t) => t.turn_id)).toEqual([3, 2, 1])
  })

  it('живой ход, которого ещё нет в загруженной ленте, остаётся первым', () => {
    let s = apply(initialState(), ev('turn_finished', { ...turn(4) }))
    s = reduce(s, { type: 'loaded', resource: 'turns', data: [turn(3), turn(2)] })
    expect(s.turns.map((t) => t.turn_id)).toEqual([4, 3, 2])
  })

  it('повторная загрузка после переподключения не плодит дублей', () => {
    let s = reduce(initialState(), { type: 'loaded', resource: 'turns', data: [turn(2), turn(1)] })
    s = apply(s, ev('turn_finished', { ...turn(3) }))
    s = reduce(s, { type: 'loaded', resource: 'turns', data: [turn(4), turn(3), turn(2), turn(1)] })
    expect(s.turns.map((t) => t.turn_id)).toEqual([4, 3, 2, 1])
  })
})

describe('reduce: колонки', () => {
  it('device_connected обновляет известную колонку', () => {
    const data = { device_id: 'aa:bb', name: 'Кухня', remote: '10.0.0.5', fw: '1.1' }
    const s = apply(withStatus(), ev('device_connected', data, 200))
    expect(s.status?.devices).toEqual([
      { device_id: 'aa:bb', name: 'Кухня', connected: true, remote: '10.0.0.5', fw: '1.1', last_seen: 200 },
    ])
  })

  it('device_connected добавляет неизвестную колонку', () => {
    const data = { device_id: 'cc:dd', name: 'cc:dd', remote: '10.0.0.6', fw: '1.0' }
    const s = apply(withStatus(), ev('device_connected', data))
    expect(s.status?.devices.map((d) => [d.device_id, d.connected])).toEqual([
      ['aa:bb', false],
      ['cc:dd', true],
    ])
  })

  it('device_disconnected помечает колонку отключённой', () => {
    let s = apply(withStatus(), ev('device_connected', { device_id: 'aa:bb', name: 'Кухня', remote: 'x', fw: '1' }))
    s = apply(s, ev('device_disconnected', { device_id: 'aa:bb' }, 300))
    expect(s.status?.devices[0]).toMatchObject({ connected: false, last_seen: 300 })
  })

  it('device_disconnected добавляет неизвестную колонку', () => {
    const s = apply(withStatus(), ev('device_disconnected', { device_id: 'ee:ff' }))
    expect(s.status?.devices[1]).toMatchObject({ device_id: 'ee:ff', name: 'ee:ff', connected: false })
  })

  it('события колонок до загрузки status не падают', () => {
    const s = apply(initialState(), ev('device_connected', { device_id: 'x', name: 'x', remote: '', fw: '' }))
    expect(s.status).toBeNull()
  })
})

describe('reduce: голоса', () => {
  const ready = (ok: boolean, error: string | null = null) =>
    ev('voice_ready', { kind: 'vosk', voice: 'big', ok, error })

  it('voice_download пишет ход скачивания', () => {
    const s = apply(initialState(), ev('voice_download', { kind: 'vosk', voice: 'big', done: 10, total: 900 }))
    expect(s.downloads).toEqual({ 'vosk/big': { done: 10, total: 900 } })
  })

  it('voice_ready ok убирает загрузку и даёт notice', () => {
    let s = apply(initialState(), ev('voice_download', { kind: 'vosk', voice: 'big', done: 1, total: null }))
    s = apply(s, ready(true))
    expect(s.downloads).toEqual({})
    expect(s.notice?.tone).toBe('ok')
  })

  it('первый неуспех даёт notice с ошибкой', () => {
    const s = apply(initialState(), ready(false, 'нет сети'))
    expect(s.notice).toEqual({ text: expect.stringContaining('нет сети'), tone: 'error' })
  })

  it('повторный неуспех того же голоса notice не даёт', () => {
    let s = apply(initialState(), ready(false, 'нет сети'))
    s = reduce(s, { type: 'dismissNotice' })
    s = apply(s, ev('voice_download', { kind: 'vosk', voice: 'big', done: 1, total: 2 }), ready(false, 'нет сети'))
    expect(s.notice).toBeNull()
    expect(s.downloads).toEqual({})
  })

  it('успех сбрасывает отметку: следующий неуспех снова даёт notice', () => {
    let s = apply(initialState(), ready(false, 'a'), ready(true))
    s = reduce(s, { type: 'dismissNotice' })
    s = apply(s, ready(false, 'b'))
    expect(s.notice?.tone).toBe('error')
  })
})

describe('reduce: изменения настроек', () => {
  it('change_applied ok убирает из pending и даёт «Применено»', () => {
    let s = reduce(initialState(), { type: 'changeSent', changeId: 7, description: 'Голос' })
    expect(s.pending).toEqual({ 7: 'Голос' })
    s = apply(s, ev('change_applied', { change_id: 7, ok: true, error: null, sections: ['tts'] }))
    expect(s.pending).toEqual({})
    expect(s.notice).toEqual({ text: 'Применено', tone: 'ok' })
  })

  it('change_applied с ошибкой даёт её текст', () => {
    let s = reduce(initialState(), { type: 'changeSent', changeId: 8, description: 'Модель' })
    s = apply(s, ev('change_applied', { change_id: 8, ok: false, error: 'нет модели', sections: [] }))
    expect(s.pending).toEqual({})
    expect(s.notice).toEqual({ text: 'нет модели', tone: 'error' })
  })

  it('change_applied раньше ответа PATCH: pending не залипает', () => {
    let s = apply(initialState(), ev('change_applied', { change_id: 9, ok: true, error: '', sections: [] }))
    s = reduce(s, { type: 'changeSent', changeId: 9, description: 'Имя' })
    expect(s.pending).toEqual({})
  })
})

describe('reduce: прочее', () => {
  it('core_state меняет status.state', () => {
    const s = apply(withStatus(), ev('core_state', { state: 'stopping' }))
    expect(s.status?.state).toBe('stopping')
  })

  it('connection offline сохраняет данные', () => {
    let s = apply(withStatus(), ev('turn_finished', { ...turn(1) }))
    s = reduce(s, { type: 'connection', connection: 'online' })
    s = reduce(s, { type: 'connection', connection: 'offline' })
    expect(s.connection).toBe('offline')
    expect(s.status).not.toBeNull()
    expect(s.turns).toHaveLength(1)
  })

  it('select, selectTurn и dismissNotice', () => {
    let s = reduce(initialState(), { type: 'select', selected: { kind: 'voice', id: 'silero/xenia' } })
    s = reduce(s, { type: 'selectTurn', turnId: 5 })
    s = reduce(s, { type: 'notice', notice: { text: 'x', tone: 'ok' } })
    s = reduce(s, { type: 'dismissNotice' })
    expect(s.selected).toEqual({ kind: 'voice', id: 'silero/xenia' })
    expect(s.selectedTurnId).toBe(5)
    expect(s.notice).toBeNull()
  })

  it('неизвестное событие не меняет состояние', () => {
    const s = initialState()
    expect(apply(s, ev('wake', { device_id: 'x', level: 3 }))).toBe(s)
  })
})
