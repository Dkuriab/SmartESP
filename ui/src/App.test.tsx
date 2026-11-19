import { render, screen } from '@testing-library/react'
import App from './App'
import { makeActions, makeState } from './components/fixtures'

const state = { current: makeState() }

vi.mock('./state/useCore', () => ({
  useCore: () => [state.current, makeActions()],
}))

describe('App', () => {
  it('рисует каркас с верхней панелью', () => {
    render(<App />)
    expect(screen.getByRole('tab', { name: 'Схема' })).toBeInTheDocument()
    expect(screen.getByText('Ядро: работает')).toBeInTheDocument()
  })

  it('ошибка отрисовки каркаса — «Что-то пошло не так»', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    state.current = makeState({ turns: null as unknown as [] })
    render(<App />)
    expect(screen.getByRole('alert')).toHaveTextContent('Что-то пошло не так')
    expect(screen.getByRole('button', { name: 'Обновить' })).toBeInTheDocument()
    state.current = makeState()
    vi.restoreAllMocks()
  })
})
