import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('рисует холст с названием', () => {
    render(<App />)
    expect(screen.getByText('SmartESP')).toBeInTheDocument()
  })
})
