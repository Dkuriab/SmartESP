import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeTurn } from '../fixtures'
import Feed from './Feed'

const executors = [{ id: 'big', name: 'Большая модель' }]

function setup(turns = [makeTurn(2), makeTurn(1)]) {
  const onSelect = vi.fn()
  const view = render(<Feed turns={turns} executors={executors} selectedId={null} onSelect={onSelect} />)
  return { onSelect, ...view }
}

describe('Feed', () => {
  it('рисует ходы в порядке состояния: новый сверху', () => {
    setup()
    const rows = screen.getAllByRole('button')
    expect(rows[0]).toHaveTextContent('вопрос 2')
    expect(rows[1]).toHaveTextContent('вопрос 1')
  })

  it('пустая лента — подсказка', () => {
    setup([])
    expect(screen.getByText('Пока нет фраз')).toBeInTheDocument()
  })

  it('длинный вопрос обрезается, полный текст в title', () => {
    const long = 'я'.repeat(2000)
    setup([makeTurn(1, { text: long })])
    const q = screen.getByTitle(long)
    expect(q).toHaveClass('cut')
    expect(q.textContent).toBe(long)
  })

  it('показывает пометки, значок тихого стиля, задержки и ошибку', () => {
    setup([
      makeTurn(1, {
        annotations: [{ source: 'speaker', text: 'Даня 0.92' }],
        style: 'quiet',
        status: 'error',
        stt_ms: 120,
        first_audio_ms: 900,
      }),
    ])
    expect(screen.getByText('Даня 0.92')).toBeInTheDocument()
    expect(screen.getByText('тихо')).toBeInTheDocument()
    expect(screen.getByText('120 / 900 мс')).toBeInTheDocument()
    expect(screen.getByText('ошибка')).toBeInTheDocument()
  })

  it('ход с передачей — метка «→ <имя цели>», неизвестная цель — по id', () => {
    const delegations = [
      { from: 'dispatcher', to: 'big', task: 'посчитай', auto: false },
      { from: 'big', to: 'ghost', task: 'проверь', auto: true },
    ]
    setup([makeTurn(1, { delegations })])
    expect(screen.getByText('→ Большая модель')).toBeInTheDocument()
    expect(screen.getByText('→ ghost')).toBeInTheDocument()
  })

  it('ход без передачи — без метки', () => {
    setup([makeTurn(1)])
    expect(screen.queryByText(/→/)).not.toBeInTheDocument()
  })

  it('карточка: «Передано: <имя> — <задача>», «(автоматически)» при auto', () => {
    const delegations = [
      { from: 'dispatcher', to: 'big', task: 'посчитай интеграл', auto: false },
      { from: 'dispatcher', to: 'big', task: 'ещё раз', auto: true },
    ]
    render(<Feed turns={[makeTurn(1, { delegations })]} executors={executors} selectedId={1} onSelect={vi.fn()} />)
    const card = screen.getByRole('dialog')
    expect(within(card).getByText('Передано: Большая модель — посчитай интеграл')).toBeInTheDocument()
    expect(within(card).getByText('Передано: Большая модель — ещё раз (автоматически)')).toBeInTheDocument()
  })

  it('показывает время хода HH:MM:SS в местном времени', () => {
    const at = new Date(2024, 0, 2, 9, 5, 7).getTime() / 1000
    setup([makeTurn(1, { at })])
    expect(screen.getByText('09:05:07')).toBeInTheDocument()
  })

  it('клик выделяет ход', async () => {
    const { onSelect } = setup()
    await userEvent.click(screen.getByText('вопрос 1'))
    expect(onSelect).toHaveBeenCalledWith(1)
  })

  it('выделенный ход открывает карточку с полным текстом', () => {
    const long = 'в'.repeat(2000)
    const turns = [makeTurn(1, { text: long, answer: 'о'.repeat(1500) })]
    render(<Feed turns={turns} executors={executors} selectedId={1} onSelect={vi.fn()} />)
    const card = screen.getByRole('dialog')
    expect(within(card).getByText(/\d\d:\d\d:\d\d/)).toBeInTheDocument()
    expect(within(card).getByText(long)).toBeInTheDocument()
    expect(within(card).getByText('о'.repeat(1500))).toBeInTheDocument()
  })

  it('закрытие карточки снимает выделение', async () => {
    const onSelect = vi.fn()
    render(<Feed turns={[makeTurn(1)]} executors={executors} selectedId={1} onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(onSelect).toHaveBeenCalledWith(null)
  })

  it('карточка хода — внутри ленты, в полной ленте тоже', () => {
    const turns = [makeTurn(1)]
    const view = render(<Feed turns={turns} executors={executors} selectedId={1} onSelect={vi.fn()} />)
    expect(screen.getByRole('dialog', { name: 'Ход' })).toHaveClass('turn-card')
    expect(screen.getByRole('dialog', { name: 'Ход' })).not.toHaveClass('turn-card-full')
    view.rerender(<Feed turns={turns} executors={executors} selectedId={1} onSelect={vi.fn()} full />)
    expect(screen.getByRole('dialog', { name: 'Ход' })).toHaveClass('turn-card', 'turn-card-full')
  })

  it('объявление: пометка «сам», текст ответа без вопроса', () => {
    setup([makeTurn(1, { turn_id: 'a3', kind: 'announcement', origin: 'core', text: '', answer: 'Пора пить воду' })])
    expect(screen.getByText('сам')).toBeInTheDocument()
    expect(screen.getByText('Пора пить воду')).toBeInTheDocument()
  })

  it('ход через API: источник и кто спрашивал', () => {
    const api = { turn_id: 'api1', device_id: 'api', device_name: 'Telegram', origin: 'api' as const }
    setup([makeTurn(1, { ...api, source: 'telegram', person: 'Аня' })])
    expect(screen.getByText('Telegram · Аня')).toBeInTheDocument()
  })

  it('не доставлено и ответ на вопрос Кузи', () => {
    setup([makeTurn(2, { status: 'undelivered' }), makeTurn(1, { origin: 'listen' })])
    expect(screen.getByText('не доставлено')).toBeInTheDocument()
    expect(screen.getByText('ответ на вопрос Кузи')).toBeInTheDocument()
  })
})

describe('Feed: инструменты', () => {
  const tools = [
    { executor: 'dispatcher', connector: 'calc', tool: 'calc_add', ok: true },
    { executor: 'dispatcher', connector: 'calc', tool: 'calc_add', ok: true },
    { executor: 'big', connector: 'notes', tool: 'note_add', ok: false },
  ]

  it('строка хода показывает вызванные инструменты без повторов, неудачный — ошибкой', () => {
    setup([makeTurn(1, { tools })])
    const add = screen.getAllByText('🧩 calc_add')
    expect(add).toHaveLength(1)
    expect(add[0]).toHaveAttribute('title', 'calc · удался')
    expect(screen.getByText('🧩 note_add')).toHaveClass('err')
  })

  it('карточка хода перечисляет все вызовы', () => {
    render(<Feed turns={[makeTurn(1, { tools })]} executors={executors} selectedId={1} onSelect={vi.fn()} />)
    const card = screen.getByRole('dialog', { name: 'Ход' })
    expect(within(card).getByText('Инструменты')).toBeInTheDocument()
    expect(within(card).getAllByText(/🧩/)).toHaveLength(3)
  })
})
