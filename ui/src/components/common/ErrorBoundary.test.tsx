import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ErrorBoundary from './ErrorBoundary'

function Broken(): never {
  throw new Error('сломалось')
}

describe('ErrorBoundary', () => {
  it('ошибка отрисовки — «Что-то пошло не так» и «Обновить»', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const onReload = vi.fn()
    render(
      <ErrorBoundary onReload={onReload}>
        <Broken />
      </ErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Что-то пошло не так')
    await userEvent.click(screen.getByRole('button', { name: 'Обновить' }))
    expect(onReload).toHaveBeenCalled()
    vi.restoreAllMocks()
  })

  it('без ошибки рисует содержимое', () => {
    render(
      <ErrorBoundary>
        <p>всё хорошо</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('всё хорошо')).toBeInTheDocument()
  })
})
