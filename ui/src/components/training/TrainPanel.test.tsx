import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { TrainJob, TrainKit } from '../../state/trainingActions'
import { makeActions } from '../fixtures'
import { bestRuns, ofTotal, runDate } from './runs'
import TrainPanel from './TrainPanel'

const kit: TrainKit = {
  id: 'wakeword',
  title: 'Слово пробуждения',
  description: '',
  record_hint: '',
  targets: [
    { id: 'kuzya', title: 'Кузя', positive: ['Кузя'], negative: [] },
    { id: 'hey_kuzya', title: 'Эй, Кузя', positive: ['Эй, Кузя'], negative: [] },
  ],
  phrases: [],
  steps: [
    { id: 'download', title: 'Скачать данные', hint: 'Один раз', per_target: false },
    { id: 'train', title: 'Обучить', hint: 'Около часа', per_target: true },
    { id: 'embed', title: 'Встроить в прошивку', hint: '', per_target: false },
  ],
}

const job = (over: Partial<TrainJob> = {}): TrainJob => ({
  kit: 'wakeword',
  step: 'train',
  target: 'hey_kuzya',
  status: 'running',
  started_at: 1000,
  finished_at: null,
  stage: 'обучение',
  done: 2500,
  total: 10000,
  error: '',
  log: ['Step #2500'],
  result: null,
  ...over,
})

const runs = [
  { run: '20261122-120000-kuzya', target: 'kuzya', title: 'Кузя', recall: 0.95, false_per_hour: 0.4, real_heard: { total: 10, detected: 9 }, cutoff: 0.9 },
  { run: '20261122-110000-kuzya', target: 'kuzya', title: 'Кузя', recall: 0.97, false_per_hour: 2.0, real_heard: { total: 10, detected: 10 }, cutoff: 0.6 },
]

describe('TrainPanel', () => {
  it('шаг цели запускается для выбранной цели; ход и «Стоп» видны', async () => {
    const actions = makeActions()
    actions.startStep = vi.fn().mockResolvedValue(job())
    render(<TrainPanel kit={kit} actions={actions} />)
    expect(screen.queryByText('Встроить в прошивку')).not.toBeInTheDocument() // встраивание — из прогонов
    await userEvent.selectOptions(screen.getByLabelText('Что обучаем'), 'hey_kuzya')
    const train = screen.getByText('Обучить').closest('li') as HTMLElement
    await userEvent.click(within(train).getByRole('button', { name: 'Запустить' }))
    expect(actions.startStep).toHaveBeenCalledWith('wakeword', 'train', 'hey_kuzya', '')
    const status = screen.getByRole('status', { name: 'Ход обучения' })
    expect(status).toHaveTextContent('Обучить · Эй, Кузя')
    expect(status).toHaveTextContent('обучение: 2500 из 10000 (25 %)')
    expect(screen.getAllByRole('button', { name: 'Запустить' })[0]).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Стоп' }))
    expect(actions.stopJob).toHaveBeenCalledWith('wakeword')
  })

  it('шаг набора — без цели; ошибка шага видна', async () => {
    const actions = makeActions()
    actions.loadJob = vi.fn().mockResolvedValue(job({ step: 'download', target: '', status: 'failed', error: 'нет места на диске' }))
    actions.startStep = vi.fn().mockResolvedValue(null)
    render(<TrainPanel kit={kit} actions={actions} />)
    expect(await screen.findByText('нет места на диске')).toBeInTheDocument()
    const download = within(screen.getByRole('list')).getByText('Скачать данные').closest('li') as HTMLElement
    await userEvent.click(within(download).getByRole('button', { name: 'Запустить' }))
    expect(actions.startStep).toHaveBeenCalledWith('wakeword', 'download', '', '')
  })

  it('прогоны: лучший помечен, «Встроить» встраивает этот прогон', async () => {
    const actions = makeActions()
    actions.loadRuns = vi.fn().mockResolvedValue(runs)
    render(<TrainPanel kit={kit} actions={actions} />)
    const best = await screen.findByText('★ 22.11 12:00')
    expect(best.closest('tr')).toHaveTextContent('9 из 10')
    await userEvent.click(within(best.closest('tr') as HTMLElement).getByRole('button', { name: 'Встроить' }))
    expect(actions.startStep).toHaveBeenCalledWith('wakeword', 'embed', '', '20261122-120000-kuzya')
  })

  it('помощники прогонов', () => {
    expect(runDate('20261122-111546-kuzya')).toBe('22.11 11:15')
    expect(ofTotal({ total: 3, false_wakes: 1 }, 'false_wakes')).toBe('1 из 3')
    expect(ofTotal(undefined, 'detected')).toBe('—')
    expect([...bestRuns(runs)]).toEqual(['20261122-120000-kuzya']) // 2 ложных в час — не лучший
  })
})
