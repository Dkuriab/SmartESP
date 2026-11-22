import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { makeActions, makeConfig, makeState, makeStatus, makeTurn } from '../components/fixtures'
import ConnectorSettings from '../components/settings/ConnectorSettings'
import SideList from '../components/side/SideList'
import type { CoreState } from '../state/model'
import { buildGraph } from './buildGraph'
import { listClients, listConnectors, withPair } from './connectors'

const connectors = [
  { id: 'notes', name: 'Заметки', command: 'uv', enabled: true },
  { id: 'telegram', name: 'Telegram-бот', command: 'uv', enabled: true, kind: 'client' },
]
const live = [
  { id: 'notes', name: 'Заметки', state: 'ready' as const, tools: ['note_add'], error: '', kind: 'mcp' as const },
  {
    id: 'telegram',
    name: 'Telegram-бот',
    state: 'ready' as const,
    tools: [],
    error: '',
    kind: 'client' as const,
    log: ['Бот запущен'],
    suggestions: [{ key: 'TELEGRAM_USERS', value: '222=Аня', text: 'Написал(а) боту: Аня (id 222)' }],
  },
]

function state(over: Partial<CoreState> = {}): CoreState {
  return makeState({ config: makeConfig({ connectors }), status: makeStatus({ connectors: live }), ...over })
}

describe('клиенты ядра', () => {
  it('бот — в разделе «Клиенты», а не среди коннекторов', () => {
    render(<SideList state={state()} actions={makeActions()} />)
    const clients = screen.getByRole('region', { name: 'Клиенты' })
    expect(within(clients).getByText('Telegram-бот')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Коннекторы' })).queryByText('Telegram-бот')).toBeNull()
    expect(listClients(state()).map((c) => c.id)).toEqual(['telegram'])
  })

  it('«Добавить» дописывает человека в список, журнал виден, инструментов нет', async () => {
    const onSave = vi.fn().mockResolvedValue('')
    const bot = listConnectors(state()).find((c) => c.id === 'telegram')!
    const settings = [{ key: 'TELEGRAM_USERS', title: 'Кому отвечать', type: 'pairs' as const, hint: '', value: '111=Данила' }]
    render(<ConnectorSettings connector={bot} applying={false} locked={false} onToggle={vi.fn()} settings={settings} onSave={onSave} />)
    expect(screen.getByText('Клиент ядра · telegram')).toBeInTheDocument()
    expect(screen.queryByText('Инструменты')).toBeNull()
    expect(screen.getByText('Бот запущен')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Добавить' }))
    expect(onSave).toHaveBeenCalledWith({ TELEGRAM_USERS: '111=Данила;222=Аня' })
  })

  it('ход из бота подсвечивает его узел и путь от него', () => {
    const turn = makeTurn(1, { source: 'telegram', device_id: '' })
    const graph = buildGraph(state({ turns: [turn], selectedTurnId: turn.turn_id }))
    const node = graph.nodes.find((n) => n.id === 'client:telegram')
    expect(node?.data).toMatchObject({ lit: true, kind: 'connector', id: 'telegram' })
    expect(graph.nodes.some((n) => n.id === 'connector:telegram')).toBe(false) // не в колонке коннекторов
    expect(graph.edges.filter((e) => e.source === 'client:telegram').every((e) => e.data?.lit)).toBe(true)
  })

  it('withPair: новая запись в конец, тот же id — заменяется', () => {
    expect(withPair('', '1=Аня')).toBe('1=Аня')
    expect(withPair('1=Аня; 2=Борис', '1=Анна')).toBe('2=Борис;1=Анна')
  })
})
