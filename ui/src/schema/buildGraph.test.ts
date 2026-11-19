import { describe, expect, it } from 'vitest'
import { makeState, makeStatus, makeTurn } from '../components/fixtures'
import type { Edge } from '@xyflow/react'
import type { Config } from '../state/model'
import { buildGraph } from './buildGraph'

const config = (stages: unknown[]): Config => ({
  effective: {
    stages,
    executors: [{ id: 'dispatcher', entry: true, model: 'qwen3' }],
    tts: { kind: 'piper', voice: 'irina' },
  },
  overridden: [],
  restart_sections: [],
  dispatcher_prompt: '',
  executor_prompts: {},
})

const node = (g: ReturnType<typeof buildGraph>, id: string) => g.nodes.find((n) => n.id === id)
const edge = (g: ReturnType<typeof buildGraph>, s: string, t: string) =>
  g.edges.find((e) => e.source === s && e.target === t)

describe('buildGraph', () => {
  it('offline device is dashed', () => {
    const g = buildGraph(makeState())
    expect(node(g, 'device:a')?.data.offline).toBe(false)
    expect(node(g, 'device:b')?.data.offline).toBe(true)
  })

  it('nameless device is labelled by MAC', () => {
    const status = makeStatus({
      devices: [{ device_id: 'aa:bb:cc', name: '', connected: true, remote: '', fw: '', protocol: 2 }],
    })
    expect(node(buildGraph(makeState({ status })), 'device:aa:bb:cc')?.data.label).toBe('aa:bb:cc')
  })

  it('config-only device is offline', () => {
    const cfg = config([])
    cfg.effective.devices = { zz: { name: 'Балкон' } }
    const g = buildGraph(makeState({ config: cfg }))
    expect(node(g, 'device:zz')?.data).toMatchObject({ label: 'Балкон', offline: true })
  })

  it('no devices gives a hint node', () => {
    const g = buildGraph(makeState({ status: makeStatus({ devices: [] }) }))
    expect(g.nodes.filter((n) => n.id.startsWith('device:'))).toHaveLength(0)
    expect(node(g, 'hint')?.data.label).toBe('Колонок пока нет: включите колонку, она появится сама')
  })

  it('without stages devices connect to dispatcher', () => {
    const g = buildGraph(makeState({ config: config([]) }))
    expect(edge(g, 'device:a', 'executor:dispatcher')).toBeTruthy()
    expect(g.nodes.some((n) => n.id.startsWith('stage:') && n.data.enabled)).toBe(false)
  })

  it('disabled known stage is shown greyed with no edges', () => {
    const g = buildGraph(makeState({ config: config([]) }))
    expect(node(g, 'stage:whisper_detect')?.data.enabled).toBe(false)
    expect(g.edges.some((e) => e.source.includes('whisper_detect') || e.target.includes('whisper_detect'))).toBe(false)
  })

  it('executor and voice labels', () => {
    const g = buildGraph(makeState({ config: config([]) }))
    expect(node(g, 'executor:dispatcher')?.data.model).toBe('qwen3')
    expect(node(g, 'voice')?.data.label).toBe('piper · irina')
  })

  it('highlights the path of a whisper turn only', () => {
    const turn = makeTurn(1, {
      device_id: 'a',
      annotations: [{ source: 'whisper_detect', text: 'шёпот' }],
    })
    const g = buildGraph(makeState({ config: config([{ kind: 'whisper_detect' }]), turns: [turn] }))
    for (const id of ['device:a', 'stage:whisper_detect', 'executor:dispatcher', 'voice'])
      expect(node(g, id)?.data.lit, id).toBe(true)
    expect(node(g, 'device:b')?.data.lit).toBe(false)
    expect(node(g, 'stage:whisper_detect')?.data.strong).toBe(true)
    expect(edge(g, 'device:a', 'stage:whisper_detect')?.data).toMatchObject({ lit: true, strong: true })
    expect(edge(g, 'stage:whisper_detect', 'executor:dispatcher')?.data).toMatchObject({ lit: true, strong: true })
    expect(edge(g, 'device:b', 'stage:whisper_detect')?.data?.lit).toBe(false)
  })

  it('selected turn wins over the latest one', () => {
    const turns = [makeTurn(2, { device_id: 'b' }), makeTurn(1, { device_id: 'a' })]
    const g = buildGraph(makeState({ turns, selectedTurnId: 1 }))
    expect(node(g, 'device:a')?.data.lit).toBe(true)
    expect(node(g, 'device:b')?.data.lit).toBe(false)
  })

  it('enabled stage without notes keeps the path lit, but not strong', () => {
    const g = buildGraph(makeState({ config: config([{ kind: 'whisper_detect' }]), turns: [makeTurn(1, { device_id: 'a' })] }))
    expect(node(g, 'stage:whisper_detect')?.data).toMatchObject({ lit: true, strong: false })
    expect(node(g, 'device:a')?.data.lit).toBe(true)
    expect(edge(g, 'device:a', 'stage:whisper_detect')?.data).toMatchObject({ lit: true, strong: false })
    expect(edge(g, 'stage:whisper_detect', 'executor:dispatcher')?.data).toMatchObject({ lit: true, strong: false })
    expect(edge(g, 'device:b', 'stage:whisper_detect')?.data?.lit).toBe(false)
  })

  it('without a turn nothing is lit', () => {
    const g = buildGraph(makeState({ config: config([{ kind: 'whisper_detect' }]) }))
    expect(node(g, 'stage:whisper_detect')?.data.lit).toBe(false)
    expect(edge(g, 'stage:whisper_detect', 'executor:dispatcher')?.data?.lit).toBe(false)
  })

  describe('executors', () => {
    const withExecs = (executors: unknown[]) => {
      const cfg = config([])
      cfg.effective.executors = executors
      return cfg
    }
    const base = [
      { id: 'dispatcher', name: 'Диспетчер', entry: true, model: 'qwen3', delegates: [{ to: 'big', when: 'сложное' }] },
      { id: 'big', name: 'Большая', model: 'r1' },
    ]
    const graph = (turns = [] as ReturnType<typeof makeTurn>[], executors: unknown[] = base) =>
      buildGraph(makeState({ config: withExecs(executors), turns }))

    it('makes executor nodes from the defaults', () => {
      const g = graph()
      expect(node(g, 'executor:dispatcher')?.data).toMatchObject({ label: 'Диспетчер', model: 'qwen3', kind: 'executor', id: 'dispatcher' })
      expect(node(g, 'executor:big')?.type).toBe('executor')
    })

    it('marks a model without tools', () => {
      const models = [{ name: 'r1', size_bytes: 1, supports_tools: false }]
      const g = buildGraph(makeState({ config: withExecs(base), models }))
      expect(node(g, 'executor:big')?.data.noTools).toBe(true)
      expect(node(g, 'executor:dispatcher')?.data.noTools).toBe(false)
    })

    it('links from a model without tools are inactive', () => {
      const models = [{ name: 'qwen3', size_bytes: 1, supports_tools: false }]
      const g = buildGraph(makeState({ config: withExecs(base), models }))
      expect(edge(g, 'executor:dispatcher', 'executor:big')?.data).toMatchObject({ inactive: true, title: 'сложное · неактивна' })
    })

    it('marks an executor whose model did not warm up', () => {
      const status = makeStatus({ executors: [{ id: 'big', ready: false, error: 'нет модели' }] })
      const g = buildGraph(makeState({ config: withExecs(base), status }))
      expect(node(g, 'executor:big')?.data.unavailable).toBe(true)
      expect(node(g, 'executor:dispatcher')?.data.unavailable).toBe(false)
    })

    it('draws a labelled link', () => {
      const e = edge(graph(), 'executor:dispatcher', 'executor:big')
      expect(e?.label).toBe('сложное')
      expect(e?.data).toMatchObject({ inactive: false, title: 'сложное' })
    })

    it('inactive link is flagged', () => {
      const ex = [{ ...base[0], delegates: [{ to: 'big', when: '' }] }, base[1]]
      expect(edge(graph([], ex), 'executor:dispatcher', 'executor:big')?.data?.inactive).toBe(true)
    })

    it('truncates a long condition, keeps the full one in title', () => {
      const when = 'я'.repeat(60)
      const ex = [{ ...base[0], delegates: [{ to: 'big', when }] }, base[1]]
      const e = edge(graph([], ex), 'executor:dispatcher', 'executor:big')
      expect(String(e?.label)).toHaveLength(40)
      expect(String(e?.label).endsWith('…')).toBe(true)
      expect(e?.data?.title).toBe(when)
    })

    it('highlights a handoff path', () => {
      const g = graph([makeTurn(1, { device_id: 'a', path: ['dispatcher', 'big'] })])
      expect(edge(g, 'executor:dispatcher', 'executor:big')?.data?.lit).toBe(true)
      expect(edge(g, 'executor:big', 'voice')?.data?.lit).toBe(true)
      expect(edge(g, 'executor:dispatcher', 'voice')?.data?.lit).toBe(false)
      expect(node(g, 'executor:big')?.data.lit).toBe(true)
    })

    it('highlights entry to voice without a handoff', () => {
      const g = graph([makeTurn(1, { device_id: 'a', path: ['dispatcher'] })])
      expect(edge(g, 'executor:dispatcher', 'voice')?.data?.lit).toBe(true)
      expect(edge(g, 'executor:dispatcher', 'executor:big')?.data?.lit).toBe(false)
      expect(node(g, 'executor:big')?.data.lit).toBe(false)
    })

    it('old turn without path stops at the entry', () => {
      const g = graph([makeTurn(1, { device_id: 'a', path: [] })])
      expect(node(g, 'executor:dispatcher')?.data.lit).toBe(true)
      expect(edge(g, 'executor:big', 'voice')?.data?.lit).toBe(false)
    })

    const three = [
      { id: 'a', name: 'A', entry: true, model: 'm', delegates: [{ to: 'b', when: 'x' }, { to: 'c', when: 'y' }] },
      { id: 'b', name: 'B', model: 'm', delegates: [{ to: 'a', when: 'z' }] },
      { id: 'c', name: 'C', model: 'm' },
    ]

    it('routes: neighbour below via bottom/top, skip and return via side loops', () => {
      const g = graph([], three)
      const down = edge(g, 'executor:a', 'executor:b')
      expect(down).toMatchObject({ sourceHandle: 'out-bottom', targetHandle: 'in-top' })
      expect(down?.type).toBeUndefined()
      const skip = edge(g, 'executor:a', 'executor:c') as Edge & { pathOptions?: { offset: number } }
      expect(skip).toMatchObject({ type: 'smoothstep', sourceHandle: 'loop-out', targetHandle: 'loop-in' })
      expect(skip.pathOptions?.offset).toBe(40)
      const up = edge(g, 'executor:b', 'executor:a') as Edge & { pathOptions?: { offset: number } }
      expect(up).toMatchObject({ type: 'smoothstep', sourceHandle: 'loop-out' })
      expect(up.pathOptions?.offset).toBe(60)
    })

    it('two-way link gets one straight edge and one loop', () => {
      const g = graph([], [{ ...base[0] }, { ...base[1], delegates: [{ to: 'dispatcher', when: 'назад' }] }])
      expect(edge(g, 'executor:dispatcher', 'executor:big')?.type).toBeUndefined()
      expect(edge(g, 'executor:big', 'executor:dispatcher')?.type).toBe('smoothstep')
    })

    it('skips self-links and duplicate targets', () => {
      const ex = [{ ...base[0], delegates: [{ to: 'dispatcher', when: 'я' }, { to: 'big', when: 'a' }, { to: 'big', when: 'b' }] }, base[1]]
      const g = graph([], ex)
      expect(edge(g, 'executor:dispatcher', 'executor:dispatcher')).toBeUndefined()
      expect(g.edges.filter((e) => e.target === 'executor:big')).toHaveLength(1)
    })

    it('empty condition uses the target description, else no label', () => {
      const ex = [{ ...base[0], delegates: [{ to: 'big', when: '' }] }, { ...base[1], description: 'расчёты' }]
      expect(edge(graph([], ex), 'executor:dispatcher', 'executor:big')?.label).toBe('расчёты')
      const none = [{ ...base[0], delegates: [{ to: 'big', when: '' }] }, base[1]]
      expect(edge(graph([], none), 'executor:dispatcher', 'executor:big')?.label).toBeUndefined()
    })
  })
})
