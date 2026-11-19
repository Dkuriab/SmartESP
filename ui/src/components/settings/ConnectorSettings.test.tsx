import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const connectors = [
  { id: 'calc', name: 'Калькулятор', command: 'uv', env: {}, enabled: true },
  { id: 'weather', name: 'Погода', command: 'uv', env: { WEATHER_PLACE: '', API_TOKEN: 'abc' }, enabled: true },
  { id: 'claude_tasks', name: 'Задачи Клоду', command: 'uv', env: { CLAUDE_TASK_FOLDERS: '' }, enabled: false },
]

function setup(id: string, over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const status = makeStatus({
    connectors: [
      { id: 'calc', name: 'Калькулятор', state: 'ready', tools: ['calc_add', 'calc_mul'], error: '' },
      { id: 'weather', name: 'Погода', state: 'failed', tools: [], error: 'Коннектор упал' },
      { id: 'claude_tasks', name: 'Задачи Клоду', state: 'disabled', tools: [], error: '' },
    ],
  })
  const state = makeState({ config: makeConfig({ connectors }), status, selected: { kind: 'connector', id }, ...over })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

describe('ConnectorSettings', () => {
  it('готовый: состояние и инструменты', () => {
    setup('calc')
    expect(screen.getByText('🧩 Калькулятор')).toBeInTheDocument()
    expect(screen.getByText('готов')).toBeInTheDocument()
    expect(screen.getByText('calc_add')).toBeInTheDocument()
    expect(screen.getByText('calc_mul')).toBeInTheDocument()
  })

  it('идущий вызов виден в состоянии', () => {
    const live = { executors: {}, connectors: { calc: { tool: 'calc_mul', executor: 'dispatcher', turn: 'a#1' } } }
    setup('calc', { live })
    expect(screen.getByText('работает: calc_mul')).toBeInTheDocument()
  })

  it('упавший: текст ошибки; окружение с секретом скрыто', () => {
    setup('weather')
    expect(screen.getByText('Коннектор упал')).toBeInTheDocument()
    expect(screen.getByText('WEATHER_PLACE')).toBeInTheDocument()
    expect(screen.getByText('не задано')).toBeInTheDocument()
    expect(screen.getByText('API_TOKEN')).toBeInTheDocument()
    expect(screen.queryByText('abc')).not.toBeInTheDocument()
    expect(screen.getByText('••••••')).toBeInTheDocument()
  })

  it('включение шлёт весь список с enabled нужного коннектора', async () => {
    const { actions } = setup('claude_tasks')
    const toggle = screen.getByRole('switch')
    expect(toggle).not.toBeChecked()
    await userEvent.click(toggle)
    expect(actions.setConnectors).toHaveBeenCalledWith(
      [connectors[0], connectors[1], { ...connectors[2], enabled: true }],
      'Задачи Клоду: включён',
    )
  })

  it('пока правка применяется — переключатель заблокирован', () => {
    setup('calc', { pending: { 1: 'Обработчики' } })
    expect(screen.getByRole('switch')).toBeDisabled()
    expect(screen.getByText('Применяется…')).toBeInTheDocument()
  })

  it('неизвестный коннектор — подсказка', () => {
    setup('ghost')
    expect(screen.getByText('Выберите блок на схеме или в списке')).toBeInTheDocument()
  })
})
