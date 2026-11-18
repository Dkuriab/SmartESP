import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeActions } from '../fixtures'
import Notice from './Notice'
import RestartBanner from './RestartBanner'
import TokenScreen from './TokenScreen'

describe('RestartBanner', () => {
  it('кнопка вызывает restart', async () => {
    const actions = makeActions()
    render(<RestartBanner onRestart={actions.restart} />)
    expect(screen.getByText('Нужен перезапуск ядра')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Перезапустить' }))
    expect(actions.restart).toHaveBeenCalled()
  })
})

describe('Notice', () => {
  it('показывает текст и закрывается', async () => {
    const onDismiss = vi.fn()
    render(<Notice notice={{ text: 'Готово', tone: 'ok' }} onDismiss={onDismiss} />)
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(onDismiss).toHaveBeenCalled()
  })
})

describe('TokenScreen', () => {
  it('передаёт введённый токен', async () => {
    const onToken = vi.fn()
    render(<TokenScreen onToken={onToken} />)
    await userEvent.type(screen.getByLabelText('Введите токен'), ' abc ')
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }))
    expect(onToken).toHaveBeenCalledWith('abc')
  })

  it('пустой токен не отправляется', async () => {
    const onToken = vi.fn()
    render(<TokenScreen onToken={onToken} />)
    await userEvent.click(screen.getByRole('button', { name: 'Войти' }))
    expect(onToken).not.toHaveBeenCalled()
  })
})
