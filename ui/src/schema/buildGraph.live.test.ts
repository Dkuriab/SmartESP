import { describe, expect, it } from 'vitest'
import { makeConfig, makeState, makeStatus, makeTurn } from '../components/fixtures'
import type { CoreState } from '../state/model'
import { buildGraph } from './buildGraph'

const connectors = [
  { id: 'calc', name: 'Калькулятор', command: 'uv', enabled: true },
  { id: 'notes', name: 'Заметки', command: 'uv', enabled: true },
  { id: 'claude_tasks', name: 'Задачи Клоду', command: 'uv', enabled: false },
]

function state(over: Partial<CoreState> = {}): CoreState {
  return makeState({
    config: makeConfig({ connectors }),
    status: makeStatus({
      ollama: { reachable: true, loaded: ['qwen3:latest'] },
      connectors: [
        { id: 'calc', name: 'Калькулятор', state: 'ready', tools: ['calc_add'], error: '', kind: 'mcp' },
        { id: 'notes', name: 'Заметки', state: 'failed', tools: [], error: 'упал', kind: 'mcp' },
        { id: 'claude_tasks', name: 'Задачи Клоду', state: 'disabled', tools: [], error: '', kind: 'mcp' },
      ],
    }),
    ...over,
  })
}

const node = (s: CoreState, id: string) => buildGraph(s).nodes.find((n) => n.id === id)
const edge = (s: CoreState, source: string, target: string) =>
  buildGraph(s).edges.find((e) => e.source === source && e.target === target)

describe('buildGraph: коннекторы', () => {
  it('узлы коннекторов — в столбце голоса, ниже него, в порядке настроек', () => {
    const g = buildGraph(state())
    const voice = g.nodes.find((n) => n.id === 'voice')
    const ids = g.nodes.filter((n) => n.type === 'connector').map((n) => n.id)
    expect(ids).toEqual(['connector:calc', 'connector:notes', 'connector:claude_tasks'])
    const calc = node(state(), 'connector:calc')
    expect(calc?.position.x).toBe(voice?.position.x)
    expect(calc?.position.y).toBeGreaterThan(voice?.position.y ?? 0)
  })

  it('состояние, ошибка и выключенный', () => {
    expect(node(state(), 'connector:calc')?.data).toMatchObject({ label: 'Калькулятор', connectorState: 'готов', warn: false })
    expect(node(state(), 'connector:notes')?.data).toMatchObject({ connectorState: 'ошибка', warn: true })
    expect(node(state(), 'connector:claude_tasks')?.data).toMatchObject({ enabled: false })
  })

  it('без вызовов стрелок к коннекторам нет', () => {
    expect(buildGraph(state()).edges.some((e) => e.target.startsWith('connector:'))).toBe(false)
  })

  it('инструменты выбранного хода подсвечивают коннектор и стрелку от вызвавшего', () => {
    const turn = makeTurn(1, { tools: [{ executor: 'dispatcher', connector: 'calc', tool: 'calc_add', ok: true, result: '' }] })
    const s = state({ turns: [turn], selectedTurnId: 1 })
    expect(node(s, 'connector:calc')?.data.lit).toBe(true)
    expect(node(s, 'connector:notes')?.data.lit).toBe(false)
    expect(edge(s, 'executor:dispatcher', 'connector:calc')?.data).toMatchObject({ lit: true, live: false })
  })
})

describe('buildGraph: живая подсветка', () => {
  const live = {
    executors: { dispatcher: { state: 'thinking' as const, turn: 'a#1' }, big: { state: 'speaking' as const, turn: 'a#1' } },
    connectors: { calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' } },
  }

  it('работающие исполнители и коннекторы получают подпись', () => {
    const s = state({ live })
    expect(node(s, 'executor:dispatcher')?.data.live).toBe('думает…')
    expect(node(s, 'executor:big')?.data.live).toBe('говорит')
    expect(node(s, 'connector:calc')?.data.live).toBe('calc_add…')
    expect(node(s, 'connector:notes')?.data.live).toBeUndefined()
  })

  it('идущий вызов рисует живую стрелку, отдельно от пути выбранного хода', () => {
    const s = state({ live, turns: [makeTurn(1, { path: ['dispatcher'] })], selectedTurnId: 1 })
    expect(edge(s, 'executor:dispatcher', 'connector:calc')?.data).toMatchObject({ live: true })
    expect(node(s, 'connector:calc')?.data.lit).toBe(false)
    // путь прошлого хода — неподвижный синий, движется только идущее сейчас
    expect(edge(s, 'executor:dispatcher', 'connector:calc')?.animated).toBe(true)
    expect(buildGraph(s).edges.filter((e) => (e.data as { lit?: boolean }).lit && !(e.data as { live?: boolean }).live).every((e) => !e.animated)).toBe(true)
  })

  it('вызов неизвестного исполнителя стрелки не даёт', () => {
    const s = state({ live: { executors: {}, connectors: { calc: { tool: 'x', executor: 'ghost', turn: 'a#1' } } } })
    expect(buildGraph(s).edges.some((e) => e.target === 'connector:calc')).toBe(false)
  })

  it('гаснущая подсветка помечена fading у узла и живой стрелки', () => {
    const fading = new Set(['connector:calc'])
    const g = buildGraph(state({ live }), fading)
    expect(g.nodes.find((n) => n.id === 'connector:calc')?.data).toMatchObject({ live: 'calc_add…', fading: true })
    expect(g.nodes.find((n) => n.id === 'executor:dispatcher')?.data.fading).toBe(false)
    expect(g.edges.find((e) => e.target === 'connector:calc')?.data).toMatchObject({ live: true, fading: true })
  })

  it('исполнитель с моделью в памяти Ollama', () => {
    expect(node(state(), 'executor:dispatcher')?.data.inMemory).toBe(true)
    expect(node(state(), 'executor:big')?.data.inMemory).toBe(false)
  })
})
