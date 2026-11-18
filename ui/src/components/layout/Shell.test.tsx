import { render, screen } from '@testing-library/react'
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
})
