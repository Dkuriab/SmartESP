import { render, screen } from '@testing-library/react'
import App from './App'
import { makeActions, makeState } from './components/fixtures'

vi.mock('./state/useCore', () => ({
  useCore: () => [makeState(), makeActions()],
}))

describe('App', () => {
  it('рисует каркас с верхней панелью', () => {
    render(<App />)
    expect(screen.getByRole('tab', { name: 'Схема' })).toBeInTheDocument()
    expect(screen.getByText('Ядро: работает')).toBeInTheDocument()
  })
})
