import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { Person, Recognition, SpeakerModel } from '../../state/peopleActions'
import { makeActions, makeState, makeStatus } from '../fixtures'
import PeopleTab from './PeopleTab'
import { describeSample, ENOUGH, PROMPTS } from './SampleRecorder'

const sample = { id: 's1', at: 1_795_000_000, device_id: 'a', seconds: 2.2, peak_db: -12 }
const anya: Person = { id: 'a1', name: 'Аня', created_at: 1, samples: [sample], stale_samples: 0, links: [] }
const model: SpeakerModel = {
  model: 'campplus',
  title: 'CAM++',
  size_mb: 28,
  ready: true,
  downloading: false,
  done_bytes: 0,
  total_bytes: null,
  error: '',
}
const seen: Recognition = { at: 1_795_000_100, device_id: 'a', turn: 4, person_id: '', name: '', score: 0.31, ms: 15 }

function setup(people: Person[] = [anya], speakerModel: SpeakerModel = model) {
  const actions = makeActions()
  actions.loadPeople = vi.fn().mockResolvedValue(people)
  actions.loadSpeakerModel = vi.fn().mockResolvedValue(speakerModel)
  actions.loadRecognitions = vi.fn().mockResolvedValue([seen])
  const devices = [{ device_id: 'a', name: 'Кухня', connected: true, remote: '', fw: '0.5.0', protocol: 4, volume: 50 }]
  render(<PeopleTab state={makeState({ status: makeStatus({ devices }) })} actions={actions} />)
  return { actions }
}

describe('PeopleTab', () => {
  it('люди, образцы, подсказка «сколько ещё» и последние узнавания', async () => {
    setup()
    expect(await screen.findByRole('button', { name: /Аня/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Образцы голоса')).toHaveTextContent('Кухня · 2.2 с · -12 дБ')
    expect(screen.getByRole('status')).toHaveTextContent(`Образцов 1 из ${ENOUGH}`)
    const table = await screen.findByRole('table')
    expect(within(table).getByText('не узнан')).toBeInTheDocument()
    expect(within(table).getByText('0.31 · 15 мс')).toBeInTheDocument()
  })

  it('запись образца: колонка уходит в ядро, подсказка фразы, итог', async () => {
    const { actions } = setup()
    actions.recordSample = vi.fn().mockResolvedValue({ ok: true, sample: { ...sample, id: 's2', peak_db: -40 } })
    await userEvent.click(await screen.findByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Записать' }))
    expect(actions.recordSample).toHaveBeenCalledWith('a1', 'a')
    expect(await screen.findByText(/тихо: подойди ближе/)).toBeInTheDocument()
    expect(actions.loadPeople).toHaveBeenCalledTimes(2) // список перечитан
    expect(PROMPTS[1]).toBeTruthy()
    expect(describeSample(sample)).toEqual({ text: 'Записано: 2.2 с · -12 дБ', warn: false })
  })

  it('добавить, переименовать и удалить человека', async () => {
    const { actions } = setup()
    actions.addPerson = vi.fn().mockResolvedValue({ ...anya, id: 'b2', name: 'Боб', samples: [] })
    actions.renamePerson = vi.fn().mockResolvedValue({ ...anya, name: 'Анна' })
    await userEvent.type(await screen.findByLabelText('Имя нового человека'), 'Боб{Enter}')
    expect(actions.addPerson).toHaveBeenCalledWith('Боб')
    const name = screen.getByLabelText('Имя')
    await userEvent.clear(name)
    await userEvent.type(name, 'Анна')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(actions.renamePerson).toHaveBeenCalledWith('a1', 'Анна')
    await userEvent.click(screen.getByRole('button', { name: 'Удалить человека' }))
    await userEvent.click(screen.getByRole('button', { name: /Удалить Анна и образцы/ }))
    expect(actions.deletePerson).toHaveBeenCalledWith('a1')
  })

  it('модели нет: плашка «Скачать», запись выключена', async () => {
    const { actions } = setup([anya], { ...model, ready: false })
    actions.downloadSpeakerModel = vi.fn().mockResolvedValue({ ...model, ready: false, downloading: true, done_bytes: 7, total_bytes: 28 })
    await userEvent.click(await screen.findByRole('button', { name: 'Скачать модель' }))
    expect(actions.downloadSpeakerModel).toHaveBeenCalled()
    expect(await screen.findByText(/Скачиваю модель узнавания голоса… 25%/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Записать' })).toBeDisabled()
  })
})
