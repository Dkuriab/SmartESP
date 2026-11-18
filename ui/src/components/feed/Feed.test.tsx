import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeTurn } from '../fixtures'
import Feed from './Feed'

function setup(turns = [makeTurn(2), makeTurn(1)]) {
  const onSelect = vi.fn()
  const view = render(<Feed turns={turns} selectedId={null} onSelect={onSelect} />)
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

  it('клик выделяет ход', async () => {
    const { onSelect } = setup()
    await userEvent.click(screen.getByText('вопрос 1'))
    expect(onSelect).toHaveBeenCalledWith(1)
  })

  it('выделенный ход открывает карточку с полным текстом', () => {
    const long = 'в'.repeat(2000)
    const turns = [makeTurn(1, { text: long, answer: 'о'.repeat(1500) })]
    render(<Feed turns={turns} selectedId={1} onSelect={vi.fn()} />)
    const card = screen.getByRole('dialog')
    expect(within(card).getByText(long)).toBeInTheDocument()
    expect(within(card).getByText('о'.repeat(1500))).toBeInTheDocument()
  })

  it('закрытие карточки снимает выделение', async () => {
    const onSelect = vi.fn()
    render(<Feed turns={[makeTurn(1)]} selectedId={1} onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(onSelect).toHaveBeenCalledWith(null)
  })
})
