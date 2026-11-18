import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeState, makeStatus } from '../fixtures'
import TopBar from './TopBar'

function setup(state = makeState(), tab: 'schema' | 'feed' = 'schema') {
  const onTab = vi.fn()
  render(<TopBar state={state} tab={tab} onTab={onTab} />)
  return { onTab }
}

describe('TopBar', () => {
  it('показывает ядро, Ollama и колонки', () => {
    setup()
    expect(screen.getByText('Ядро: работает')).toBeInTheDocument()
    expect(screen.getByText('Ollama ✓')).toBeInTheDocument()
    expect(screen.getByText('Колонки 1 из 2')).toBeInTheDocument()
  })

  it('прогрев и остановка', () => {
    setup(makeState({ status: makeStatus({ state: 'warming' }) }))
    expect(screen.getByText('Ядро: прогревается')).toBeInTheDocument()
  })

  it('Ollama недоступна', () => {
    setup(makeState({ status: makeStatus({ ollama: { reachable: false, loaded: [] } }) }))
    expect(screen.getByText('Ollama ✗')).toBeInTheDocument()
  })

  it('offline показывает «Нет связи с ядром»', () => {
    setup(makeState({ connection: 'offline' }))
    expect(screen.getByText('Нет связи с ядром')).toBeInTheDocument()
  })

  it('без данных не падает', () => {
    setup(makeState({ status: null, connection: 'connecting' }))
    expect(screen.getByText('Подключение…')).toBeInTheDocument()
  })

  it('вкладки переключаются', async () => {
    const { onTab } = setup()
    await userEvent.click(screen.getByRole('tab', { name: 'Лента' }))
    expect(onTab).toHaveBeenCalledWith('feed')
  })
})
