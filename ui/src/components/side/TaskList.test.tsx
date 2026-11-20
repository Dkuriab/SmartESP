import { act, render, screen, within } from '@testing-library/react'
import type { Task } from '../../state/model'
import TaskList from './TaskList'

const NOW = 2_000_000

function task(over: Partial<Task> = {}): Task {
  return {
    key: 'connector:timers/t1',
    source: 'connector:timers',
    id: 't1',
    title: 'Таймер «картошка»',
    status: 'running',
    started_at: NOW / 1000 - 120,
    eta: NOW / 1000 + 300,
    finished_at: null,
    device_id: 'aa',
    device_name: 'Кухня',
    person: 'Аня',
    result: '',
    ...over,
  }
}

describe('TaskList', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })
  afterEach(() => vi.useRealTimers())

  const names = (id: string) => (id === 'timers' ? 'Таймеры' : undefined)

  it('нет задач — раздела нет', () => {
    render(<TaskList tasks={[]} connectorName={names} />)
    expect(screen.queryByRole('region', { name: 'В работе' })).toBeNull()
  })

  it('задача: что, откуда и для кого, сколько идёт и сколько ещё; отсчёт тикает', () => {
    render(<TaskList tasks={[task()]} connectorName={names} />)
    const section = screen.getByRole('region', { name: 'В работе' })
    expect(within(section).getByText('В работе 1')).toBeInTheDocument()
    expect(within(section).getByText('Таймер «картошка»')).toBeInTheDocument()
    expect(within(section).getByText('Таймеры · Кухня · Аня')).toBeInTheDocument()
    expect(within(section).getByText('идёт 2 мин · ещё 5 мин')).toBeInTheDocument()
    act(() => vi.advanceTimersByTime(60_000))
    expect(within(section).getByText('идёт 3 мин · ещё 4 мин')).toBeInTheDocument()
  })

  it('законченная видна с итогом, угасает и уходит', () => {
    const done = task({ status: 'done', finished_at: NOW / 1000, result: 'сработал' })
    render(<TaskList tasks={[done]} connectorName={names} />)
    const item = screen.getByText('готово').closest('li')
    expect(item).not.toHaveClass('fade')
    act(() => vi.advanceTimersByTime(27_000))
    expect(screen.getByText('готово').closest('li')).toHaveClass('fade')
    act(() => vi.advanceTimersByTime(5_000))
    expect(screen.queryByRole('region', { name: 'В работе' })).toBeNull()
  })
})
