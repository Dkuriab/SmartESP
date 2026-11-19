import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeActions } from '../fixtures'
import Notice from './Notice'
import RestartBanner from './RestartBanner'
import TokenScreen from './TokenScreen'

describe('RestartBanner', () => {
  it('кнопка вызывает restart', async () => {
    const actions = makeActions()
    render(<RestartBanner onRestart={actions.restart} restarting={false} online />)
    expect(screen.getByText('Нужен перезапуск ядра')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Перезапустить' }))
    expect(actions.restart).toHaveBeenCalled()
  })

  it('после нажатия кнопка неактивна до переподключения', () => {
    render(<RestartBanner onRestart={vi.fn()} restarting online />)
    expect(screen.getByRole('button', { name: 'Перезапускается…' })).toBeDisabled()
  })

  it('без связи кнопка неактивна', () => {
    render(<RestartBanner onRestart={vi.fn()} restarting={false} online={false} />)
    expect(screen.getByRole('button', { name: 'Перезапустить' })).toBeDisabled()
  })
})

describe('Notice', () => {
  afterEach(() => vi.useRealTimers())

  it('показывает текст и закрывается', async () => {
    const onDismiss = vi.fn()
    render(<Notice notice={{ text: 'Готово', tone: 'ok' }} onDismiss={onDismiss} />)
    expect(screen.getByRole('status')).toHaveTextContent('Готово')
    await userEvent.click(screen.getByRole('button', { name: 'Закрыть' }))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('«ok» закрывается сам через 4 с, таймер снимается с уведомлением', () => {
    vi.useFakeTimers()
    const onDismiss = vi.fn()
    const { unmount } = render(<Notice notice={{ text: 'Применено', tone: 'ok' }} onDismiss={onDismiss} />)
    vi.advanceTimersByTime(3_900)
    expect(onDismiss).not.toHaveBeenCalled()
    vi.advanceTimersByTime(200)
    expect(onDismiss).toHaveBeenCalledTimes(1)
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('новое уведомление начинает отсчёт заново', () => {
    vi.useFakeTimers()
    const onDismiss = vi.fn()
    const { rerender } = render(<Notice notice={{ text: 'a', tone: 'ok' }} onDismiss={onDismiss} />)
    vi.advanceTimersByTime(3_000)
    rerender(<Notice notice={{ text: 'b', tone: 'ok' }} onDismiss={onDismiss} />)
    vi.advanceTimersByTime(3_000)
    expect(onDismiss).not.toHaveBeenCalled()
  })

  it('ошибка — role="alert" и сама не закрывается', () => {
    vi.useFakeTimers()
    const onDismiss = vi.fn()
    render(<Notice notice={{ text: 'Сбой', tone: 'error' }} onDismiss={onDismiss} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Сбой')
    vi.advanceTimersByTime(60_000)
    expect(onDismiss).not.toHaveBeenCalled()
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
