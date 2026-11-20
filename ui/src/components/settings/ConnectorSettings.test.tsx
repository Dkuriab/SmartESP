import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const connectors = [
  { id: 'calc', name: 'Калькулятор', command: 'uv', env: {}, enabled: true },
  { id: 'weather', name: 'Погода', command: 'uv', env: { WEATHER_PLACE: '', API_TOKEN: 'abc' }, enabled: true },
  { id: 'claude_tasks', name: 'Задачи Клоду', command: 'uv', env: { CLAUDE_TASK_FOLDERS: '' }, enabled: false },
]

const text = (key: string, title: string, value: string, hint = '') => ({ key, title, type: 'text' as const, hint, value })
const details = [
  {
    id: 'weather',
    name: 'Погода',
    state: 'failed' as const,
    tools: [],
    error: '',
    settings: [text('WEATHER_PLACE', 'Город', '', 'например, Москва')],
    note: '',
    example: '',
  },
  {
    id: 'calc',
    name: 'Калькулятор',
    state: 'ready' as const,
    tools: [],
    error: '',
    settings: [],
    note: 'Папки и инструменты Клода настраиваются только в config.yaml',
    example: 'connectors:\n  - id: claude_tasks',
  },
  {
    id: 'claude_tasks',
    name: 'Задачи Клоду',
    state: 'disabled' as const,
    tools: [],
    error: '',
    settings: [
      { key: 'CLAUDE_TASK_FOLDERS', title: 'Папки для задач', type: 'list' as const, hint: '', value: 'дом=/tmp/h' },
      { key: 'OFF', title: 'Open Food Facts', type: 'flag' as const, hint: '', value: '' },
      { key: 'PIN', title: 'Пин', type: 'secret' as const, hint: '', value: '•••' },
    ],
    note: '',
    example: '',
  },
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
  const selected = { kind: 'connector' as const, id }
  const state = makeState({ config: makeConfig({ connectors }), status, connectors: details, selected, ...over })
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

  it('упавший: текст ошибки; необъявленное окружение — только показ, секрет скрыт', () => {
    setup('weather', { connectors: null })
    expect(screen.getByText('Коннектор упал')).toBeInTheDocument()
    expect(screen.getByText('WEATHER_PLACE')).toBeInTheDocument()
    expect(screen.getByText('не задано')).toBeInTheDocument()
    expect(screen.getByText('API_TOKEN')).toBeInTheDocument()
    expect(screen.queryByText('abc')).not.toBeInTheDocument()
    expect(screen.getByText('••••••')).toBeInTheDocument()
  })

  it('включение шлёт весь список с enabled нужного коннектора', async () => {
    const { actions } = setup('claude_tasks')
    const toggle = screen.getByRole('switch', { name: 'Включён' })
    expect(toggle).not.toBeChecked()
    await userEvent.click(toggle)
    expect(actions.setConnectors).toHaveBeenCalledWith([{ id: 'claude_tasks', enabled: true }], 'Задачи Клоду: включён')
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

  it('объявленная настройка — поле формы с подсказкой; сохранение шлёт изменённое', async () => {
    const { actions } = setup('weather')
    expect(screen.queryByText('WEATHER_PLACE')).not.toBeInTheDocument() // в форме, не в окружении
    expect(screen.getByText('например, Москва')).toBeInTheDocument()
    const save = screen.getByRole('button', { name: 'Сохранить' })
    expect(save).toBeDisabled() // ничего не изменено
    await userEvent.type(screen.getByLabelText('Город'), 'Тверь')
    await userEvent.click(save)
    expect(actions.saveConnectorEnv).toHaveBeenCalledWith('weather', { WEATHER_PLACE: 'Тверь' }, 'Погода: настройки')
  })

  it('ошибка ядра — у формы', async () => {
    const { actions } = setup('weather')
    vi.mocked(actions.saveConnectorEnv).mockResolvedValue('WEATHER_PLACE: значение в одну строку')
    await userEvent.type(screen.getByLabelText('Город'), 'Тверь')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('WEATHER_PLACE: значение в одну строку'))
  })

  it('список папок, флаг и секрет; неверный путь не уходит', async () => {
    const { actions } = setup('claude_tasks')
    expect(screen.getByLabelText('Папки для задач: имя 1')).toHaveValue('дом')
    expect(screen.getByLabelText('Пин')).toHaveAttribute('type', 'password')
    expect(screen.getByLabelText('Пин')).toHaveValue('') // маска не в поле: ввод не склеится с «•••»
    expect(screen.getByLabelText('Пин')).toHaveAttribute('placeholder', 'задано — введите новое')
    await userEvent.click(screen.getByRole('button', { name: '+ папка' }))
    await userEvent.type(screen.getByLabelText('Папки для задач: имя 2'), 'работа')
    await userEvent.type(screen.getByLabelText('Папки для задач: путь 2'), 'relative')
    await userEvent.click(screen.getByRole('switch', { name: 'Open Food Facts' }))
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Папки для задач: Путь «relative» должен начинаться с / или ~/')
    expect(actions.saveConnectorEnv).not.toHaveBeenCalled()
    await userEvent.clear(screen.getByLabelText('Папки для задач: путь 2'))
    await userEvent.type(screen.getByLabelText('Папки для задач: путь 2'), '~/w')
    await userEvent.click(screen.getByRole('button', { name: 'Убрать папку 1' }))
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить' }))
    expect(actions.saveConnectorEnv).toHaveBeenCalledWith(
      'claude_tasks',
      { CLAUDE_TASK_FOLDERS: 'работа=~/w', OFF: '1' },
      'Задачи Клоду: настройки',
    )
  })

  it('пока правка применяется — форма заблокирована', () => {
    setup('weather', { pending: { 1: 'Обработчики' } })
    expect(screen.getByLabelText('Город')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Сохранить' })).toBeDisabled()
  })

  it('пояснение коннектора и пример для config.yaml — только показ, без формы', () => {
    setup('calc')
    expect(screen.getByText('Папки и инструменты Клода настраиваются только в config.yaml')).toBeInTheDocument()
    expect(screen.getByText(/id: claude_tasks/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Сохранить' })).not.toBeInTheDocument()
  })
})
