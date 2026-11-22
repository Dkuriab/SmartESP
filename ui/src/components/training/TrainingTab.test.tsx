import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { TrainKit } from '../../state/trainingActions'
import { makeActions, makeState, makeStatus } from '../fixtures'
import { describeRecording } from './RecordPanel'
import { goalFor } from './PhraseTable'
import TrainingTab from './TrainingTab'

const kit: TrainKit = {
  id: 'wakeword',
  title: 'Слово пробуждения',
  description: 'Модель для колонки',
  record_hint: 'Говори как обычно',
  targets: [{ id: 'kuzya', title: 'Кузя', positive: ['Кузя', 'Кузьма'], negative: ['Вася'] }],
  phrases: [
    { phrase: 'Кузя', people: { Данила: 50 } },
    { phrase: 'Кузьма', people: {} },
    { phrase: 'Вася', people: { Данила: 3 } },
  ],
}

function setup() {
  const actions = makeActions()
  actions.loadTraining = vi.fn().mockResolvedValue([kit])
  const devices = [{ device_id: 'a', name: 'Кухня', connected: true, remote: '', fw: '0.4.0', protocol: 3 }]
  render(<TrainingTab state={makeState({ status: makeStatus({ devices }) })} actions={actions} />)
  return { actions }
}

describe('TrainingTab', () => {
  it('набор: цели, счёт записей по людям и цель на человека', async () => {
    setup()
    expect(await screen.findByRole('button', { name: 'Слово пробуждения' })).toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('50 / 50')).toHaveClass('done')
    expect(within(table).getByText('3 / 20')).not.toHaveClass('done')
    expect(goalFor(kit, 'Кузьма')).toBe(30)
  })

  it('фраза добавляется в «Не откликаться на» по Enter и уходит в ядро', async () => {
    const { actions } = setup()
    const input = await screen.findByLabelText('Не откликаться на: добавить фразу')
    await userEvent.type(input, ' Кузов {Enter}')
    expect(actions.saveTargets).toHaveBeenCalledWith('wakeword', [{ ...kit.targets[0], negative: ['Вася', 'Кузов'] }])
    await userEvent.click(screen.getByRole('button', { name: 'Убрать «Кузьма»' }))
    expect(actions.saveTargets).toHaveBeenLastCalledWith('wakeword', [{ ...kit.targets[0], positive: ['Кузя'] }])
  })

  it('запись: колонка, голос и фраза уходят в ядро; итог и отказ видны', async () => {
    const { actions } = setup()
    actions.recordPhrase = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, recording: { name: '0051.wav', seconds: 0.9, peak_db: -12 } })
      .mockResolvedValueOnce({ ok: false, text: 'колонка ничего не услышала' })
    await userEvent.type(await screen.findByLabelText('Чей голос'), 'Данила')
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }))
    expect(actions.recordPhrase).toHaveBeenCalledWith({ kit: 'wakeword', deviceId: 'a', phrase: 'Кузя', person: 'Данила' })
    expect(await screen.findByText(/Записано 0051.wav · 0.9 с · -12 дБ/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }))
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('колонка ничего не услышала'))
  })

  it('подсказки к записи: тихо и длинно', () => {
    expect(describeRecording({ name: '1', seconds: 1, peak_db: -40 }).warn).toBe(true)
    expect(describeRecording({ name: '1', seconds: 4, peak_db: -10 }).text).toMatch(/длинная/)
    expect(describeRecording({ name: '1', seconds: 1, peak_db: -10 }).warn).toBe(false)
  })
})
