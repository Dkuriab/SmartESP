import type { CoreEvent } from '../api/events'
import type { Task } from './model'
import { initialState } from './model'
import { reduce } from './reducer'
import { FINISHED_VISIBLE_MS, MAX_TASKS, fading, shortDuration, sourceLabel, taskTiming, trimTasks, visibleTasks } from './tasks'

function task(over: Partial<Task> = {}): Task {
  return {
    key: 'connector:timers/t1',
    source: 'connector:timers',
    id: 't1',
    title: 'Таймер «картошка»',
    status: 'running',
    started_at: 1000,
    eta: 1600,
    finished_at: null,
    device_id: '',
    device_name: '',
    person: 'Аня',
    result: '',
    ...over,
  }
}

const event = (kind: string, data: Task): CoreEvent => ({ kind, data: data as unknown as Record<string, unknown>, at: 0 })

describe('tasks', () => {
  it('лишние задачи — самые старые законченные; идущая не выпадает', () => {
    const running = task({ key: 'connector:timers/old', started_at: 1 })
    const finished = Array.from({ length: MAX_TASKS + 5 }, (_, i) =>
      task({ key: `connector:timers/f${i}`, status: 'done', finished_at: 2000 + i }),
    )
    const kept = trimTasks([running, ...finished])
    expect(kept).toHaveLength(MAX_TASKS)
    expect(kept.some((t) => t.key === 'connector:timers/old')).toBe(true)
    expect(kept.some((t) => t.key === 'connector:timers/f0')).toBe(false)
    expect(kept.some((t) => t.key === `connector:timers/f${MAX_TASKS + 4}`)).toBe(true)
  })

  it('события task_*: новая в конец, обновление и конец — на месте по ключу', () => {
    let state = reduce(initialState(), { type: 'event', event: event('task_started', task()) })
    state = reduce(state, { type: 'event', event: event('task_started', task({ key: 'late_answer/k#1', source: 'late_answer' })) })
    state = reduce(state, { type: 'event', event: event('task_finished', task({ status: 'done', finished_at: 1600 })) })
    expect(state.tasks.map((t) => [t.key, t.status])).toEqual([
      ['connector:timers/t1', 'done'],
      ['late_answer/k#1', 'running'],
    ])
  })

  it('событие без ключа или с неизвестным состоянием — мимо', () => {
    const bad = { ...task(), status: 'спит' } as unknown as Task
    const state = reduce(initialState(), { type: 'event', event: event('task_started', bad) })
    expect(state.tasks).toEqual([])
  })

  it('загрузка GET /tasks заменяет список', () => {
    const state = reduce(initialState(), { type: 'loaded', resource: 'tasks', data: [task()] })
    expect(state.tasks).toHaveLength(1)
  })

  it('видимые: идущие старые первыми, затем недавно законченные; старые законченные скрыты и угасают', () => {
    const now = 2000 * 1000
    const tasks = [
      task({ key: 'b', started_at: 1500 }),
      task({ key: 'a', started_at: 1200 }),
      task({ key: 'done', status: 'done', finished_at: 1995 }),
      task({ key: 'old', status: 'done', finished_at: 2000 - FINISHED_VISIBLE_MS / 1000 - 1 }),
    ]
    expect(visibleTasks(tasks, now).map((t) => t.key)).toEqual(['a', 'b', 'done'])
    const done = task({ key: 'done', status: 'done', finished_at: 1995 })
    expect(fading(done, now)).toBe(false)
    expect(fading(done, now + 27_000)).toBe(true)
  })

  it('время: идёт и сколько до срока; итог законченной', () => {
    expect(taskTiming(task(), 1100 * 1000)).toBe('идёт 1 мин · ещё 8 мин')
    expect(taskTiming(task({ eta: null }), 1030 * 1000)).toBe('идёт 30 с')
    expect(taskTiming(task(), 1700 * 1000)).toBe('идёт 11 мин · срок прошёл')
    expect(taskTiming(task({ status: 'failed' }), 0)).toBe('не удалось')
    expect(shortDuration(3900)).toBe('1 ч 05 мин')
  })

  it('источник: ответ модели, имя коннектора или id', () => {
    const names = (id: string) => (id === 'timers' ? 'Таймеры' : undefined)
    expect(sourceLabel('late_answer', names)).toBe('ответ модели')
    expect(sourceLabel('connector:timers', names)).toBe('Таймеры')
    expect(sourceLabel('connector:x', names)).toBe('x')
  })
})
