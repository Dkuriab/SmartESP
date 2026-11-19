import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeActions, makeState, makeStatus, makeTurn } from '../fixtures'
import Shell from './Shell'

describe('Shell', () => {
  it('плашка перезапуска вызывает actions.restart', async () => {
    const actions = makeActions()
    const state = makeState({ status: makeStatus({ restart_required: true }) })
    render(<Shell state={state} actions={actions} />)
    await userEvent.click(screen.getByRole('button', { name: 'Перезапустить' }))
    expect(actions.restart).toHaveBeenCalled()
  })

  it('без перезапуска плашки нет', () => {
    render(<Shell state={makeState()} actions={makeActions()} />)
    expect(screen.queryByText('Нужен перезапуск ядра')).not.toBeInTheDocument()
  })

  it('unauthorized показывает экран токена', () => {
    render(<Shell state={makeState({ connection: 'unauthorized' })} actions={makeActions()} />)
    expect(screen.getByLabelText('Введите токен')).toBeInTheDocument()
  })

  it('offline не пустеет: последние ходы остаются', () => {
    const state = makeState({ connection: 'offline', turns: [makeTurn(1)] })
    render(<Shell state={state} actions={makeActions()} />)
    expect(screen.getByText('Нет связи с ядром')).toBeInTheDocument()
    expect(screen.getByText('вопрос 1')).toBeInTheDocument()
  })

  it('вкладка «Лента» разворачивает ленту, «Схема» возвращает панели', async () => {
    render(<Shell state={makeState()} actions={makeActions()} />)
    expect(screen.getByLabelText('Настройки')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Лента' }))
    expect(screen.queryByLabelText('Настройки')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Схема' }))
    expect(screen.getByLabelText('Настройки')).toBeInTheDocument()
  })

  it('вкладка «Ядро» прячет схему и ленту и показывает журнал', async () => {
    render(<Shell state={makeState({ turns: [makeTurn(1)] })} actions={makeActions()} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Ядро' }))
    expect(screen.queryByLabelText('Настройки')).not.toBeInTheDocument()
    expect(screen.queryByText('вопрос 1')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Журнал')).toBeInTheDocument()
  })

  it('клик по ходу выделяет его через actions.selectTurn', async () => {
    const actions = makeActions()
    render(<Shell state={makeState({ turns: [makeTurn(7)] })} actions={actions} />)
    await userEvent.click(screen.getByText('вопрос 7'))
    expect(actions.selectTurn).toHaveBeenCalledWith(7)
  })

  it('уведомление закрывается через actions.dismissNotice', async () => {
    const actions = makeActions()
    render(<Shell state={makeState({ notice: { text: 'Ошибка', tone: 'error' } })} actions={actions} />)
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(actions.dismissNotice).toHaveBeenCalled()
  })

  it('узкий экран: «Список» и «Настройки» открывают панели поверх схемы', async () => {
    render(<Shell state={makeState()} actions={makeActions()} />)
    const list = screen.getByRole('button', { name: 'Список' })
    expect(list).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByLabelText('Список')).not.toHaveClass('open')
    await userEvent.click(list)
    expect(list).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('complementary', { name: 'Список' })).toHaveClass('open')
    await userEvent.click(screen.getByRole('button', { name: 'Настройки' }))
    expect(screen.getByRole('complementary', { name: 'Список' })).not.toHaveClass('open')
    expect(screen.getByRole('complementary', { name: 'Настройки' })).toHaveClass('open')
    await userEvent.click(screen.getByRole('button', { name: 'Настройки' }))
    expect(screen.getByRole('complementary', { name: 'Настройки' })).not.toHaveClass('open')
  })

  it('выбор блока в открытом списке открывает его настройки', async () => {
    const actions = makeActions()
    render(<Shell state={makeState()} actions={actions} />)
    await userEvent.click(screen.getByRole('button', { name: 'Список' }))
    const list = screen.getByRole('complementary', { name: 'Список' })
    await userEvent.click(within(list).getByRole('button', { name: /Кухня/ }))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'device', id: 'a' })
    expect(screen.getByRole('complementary', { name: 'Настройки' })).toHaveClass('open')
  })

  it('во вкладке «Лента» переключателей панелей нет', async () => {
    render(<Shell state={makeState()} actions={makeActions()} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Лента' }))
    expect(screen.queryByRole('button', { name: 'Список' })).not.toBeInTheDocument()
  })
})
