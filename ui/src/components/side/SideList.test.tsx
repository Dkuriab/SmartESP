import { act, render, screen, within } from '@testing-library/react'
import { LIVE_MIN_MS } from '../../schema/linger'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SideList from './SideList'

function setup(over: Partial<CoreState> = {}) {
  const actions = makeActions()
  render(<SideList state={makeState({ config: makeConfig(), ...over })} actions={actions} />)
  return { actions }
}

const section = (name: string) => screen.getByRole('region', { name })

describe('SideList', () => {
  it('колонки с точкой «в сети», клик выбирает колонку', async () => {
    const { actions } = setup()
    const devices = section('Колонки 2')
    expect(within(devices).getByLabelText('в сети')).toBeInTheDocument()
    expect(within(devices).getByLabelText('не в сети')).toBeInTheDocument()
    await userEvent.click(within(devices).getByRole('button', { name: /Спальня/ }))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'device', id: 'b' })
  })

  it('колонка без имени подписана MAC; ноль колонок — подсказка', () => {
    setup({ status: makeStatus({ devices: [{ device_id: 'aa:bb', name: '', connected: true, remote: '', fw: '', protocol: 2 }] }) })
    expect(screen.getByRole('button', { name: /aa:bb/ })).toBeInTheDocument()
  })

  it('ноль колонок — «Колонок пока нет»', () => {
    setup({ status: makeStatus({ devices: [] }) })
    expect(screen.getByText('Колонок пока нет')).toBeInTheDocument()
  })

  it('обработчики: переключатель шлёт список без обработчика, клик по имени выбирает', async () => {
    const { actions } = setup()
    const stages = section('Обработчики')
    await userEvent.click(within(stages).getByRole('switch', { name: 'Шёпот' }))
    expect(actions.setStages).toHaveBeenCalledWith([])
    expect(actions.select).not.toHaveBeenCalled()
    await userEvent.click(within(stages).getByRole('button', { name: /Шёпот/ }))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'stage', id: 'whisper_detect' })
  })

  it('настройки ещё не загружены — переключатели обработчиков неактивны', () => {
    setup({ config: null })
    expect(within(section('Обработчики')).getByRole('switch', { name: 'Шёпот' })).toBeDisabled()
  })

  it('голос показывает текущий голос, выбирается кликом', async () => {
    const { actions } = setup({ selected: { kind: 'voice', id: 'voice' } })
    const voice = screen.getByRole('button', { name: /Голос/ })
    expect(voice).toHaveTextContent('piper · irina')
    expect(voice).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(voice)
    expect(actions.select).toHaveBeenCalledWith({ kind: 'voice', id: 'voice' })
  })

  it('исполнители: имя (или id) и модель, входной первым, клик выбирает', async () => {
    const executors = [
      { id: 'big', name: 'Большая модель', entry: false, model: 'gpt-oss' },
      { id: 'dispatcher', name: 'Диспетчер', entry: true, model: 'qwen3' },
      { id: 'executor-1', name: '', entry: false, model: 'gemma3' },
    ]
    const { actions } = setup({ config: makeConfig({ executors }), selected: { kind: 'executor', id: 'big' } })
    const rows = within(section('Исполнители')).getAllByRole('button').filter((b) => b.classList.contains('row-main'))
    expect(rows.map((r) => r.textContent)).toEqual(['⚡️Диспетчерqwen3', '🧠Большая модельgpt-oss', '🧠executor-1gemma3'])
    expect(rows[1]).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(rows[0]!)
    expect(actions.select).toHaveBeenCalledWith({ kind: 'executor', id: 'dispatcher' })
  })

  it('«Добавить» создаёт исполнителя и выбирает его', async () => {
    const { actions } = setup()
    vi.mocked(actions.addExecutor).mockResolvedValue('executor-1')
    await userEvent.click(within(section('Исполнители')).getByRole('button', { name: 'Добавить' }))
    expect(actions.addExecutor).toHaveBeenCalledTimes(1)
    expect(actions.select).toHaveBeenCalledWith({ kind: 'executor', id: 'executor-1' })
  })

  it('«Добавить» не принят — выбор не меняется', async () => {
    const { actions } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }))
    expect(actions.select).not.toHaveBeenCalled()
  })

  it('«Добавить» заблокирована, пока применяется или нет настроек', () => {
    setup({ pending: { 1: 'x' } })
    expect(screen.getByRole('button', { name: 'Добавить' })).toBeDisabled()
  })

  it('внизу — «Доступ из сети»', async () => {
    setup()
    expect(await screen.findByText('Адрес в сети не найден')).toBeInTheDocument()
  })
})

describe('SideList: коннекторы и живая подсветка', () => {
  const connectors = [
    { id: 'calc', name: 'Калькулятор', command: 'uv', enabled: true },
    { id: 'notes', name: 'Заметки', command: 'uv', enabled: true },
  ]
  const status = makeStatus({
    connectors: [
      { id: 'calc', name: 'Калькулятор', state: 'ready', tools: ['calc_add'], error: '', kind: 'mcp' },
      { id: 'notes', name: 'Заметки', state: 'failed', tools: [], error: 'упал', kind: 'mcp' },
    ],
  })

  function draw(over: Partial<CoreState> = {}) {
    const actions = makeActions()
    render(<SideList state={makeState({ config: makeConfig({ connectors }), status, ...over })} actions={actions} />)
    return { actions }
  }

  it('без коннекторов раздела нет', () => {
    setup()
    expect(screen.queryByRole('region', { name: 'Коннекторы' })).not.toBeInTheDocument()
  })

  it('переключатель выключает коннектор, упавший отмечен', async () => {
    const { actions } = draw()
    const list = section('Коннекторы')
    expect(within(list).getByLabelText('ошибка')).toBeInTheDocument()
    await userEvent.click(within(list).getByRole('switch', { name: 'Калькулятор' }))
    expect(actions.setConnectors).toHaveBeenCalledWith([{ id: 'calc', enabled: false }], 'Калькулятор: выключен')
  })

  it('работающие исполнитель и коннектор отмечены точкой с подписью', () => {
    const live = {
      executors: { dispatcher: { state: 'speaking' as const, turn: 'a#1' } },
      connectors: { calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' } },
    }
    draw({ live })
    expect(within(section('Исполнители')).getByLabelText('говорит')).toBeInTheDocument()
    expect(within(section('Коннекторы')).getByLabelText('calc_add…')).toBeInTheDocument()
  })

  it('вызов, начавшийся и кончившийся в одном кадре, отмечен точкой не меньше LIVE_MIN_MS', () => {
    vi.useFakeTimers()
    const state = makeState({ config: makeConfig({ connectors }), status })
    const view = render(<SideList state={state} actions={makeActions()} />)
    const call = { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' }
    const flashed = { ...state, live: { executors: {}, connectors: {}, seq: 1, started: { 'connector:calc': { seq: 1, value: call } } } }
    view.rerender(<SideList state={flashed} actions={makeActions()} />)
    expect(within(section('Коннекторы')).getByLabelText('calc_add…')).toBeInTheDocument()
    act(() => void vi.advanceTimersByTime(LIVE_MIN_MS))
    expect(within(section('Коннекторы')).queryByLabelText('calc_add…')).not.toBeInTheDocument()
    vi.useRealTimers()
  })
})
