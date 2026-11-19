import { describe, expect, it } from 'vitest'
import { makeState, makeStatus, makeTurn } from '../components/fixtures'
import type { Config } from '../state/model'
import { buildGraph } from './buildGraph'

const config = (stages: unknown[]): Config => ({
  effective: {
    stages,
    executors: [{ entry: true, model: 'qwen3' }],
    tts: { kind: 'piper', voice: 'irina' },
  },
  overridden: [],
  restart_sections: [],
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
      devices: [{ device_id: 'aa:bb:cc', name: '', connected: true, remote: '', fw: '' }],
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
    expect(edge(g, 'device:a', 'dispatcher')).toBeTruthy()
    expect(g.nodes.some((n) => n.id.startsWith('stage:') && n.data.enabled)).toBe(false)
  })

  it('disabled known stage is shown greyed with no edges', () => {
    const g = buildGraph(makeState({ config: config([]) }))
    expect(node(g, 'stage:whisper_detect')?.data.enabled).toBe(false)
    expect(g.edges.some((e) => e.source.includes('whisper_detect') || e.target.includes('whisper_detect'))).toBe(false)
  })

  it('dispatcher and voice labels', () => {
    const g = buildGraph(makeState({ config: config([]) }))
    expect(node(g, 'dispatcher')?.data.label).toBe('qwen3')
    expect(node(g, 'voice')?.data.label).toBe('piper · irina')
  })

  it('highlights the path of a whisper turn only', () => {
    const turn = makeTurn(1, {
      device_id: 'a',
      annotations: [{ source: 'whisper_detect', text: 'шёпот' }],
    })
    const g = buildGraph(makeState({ config: config([{ kind: 'whisper_detect' }]), turns: [turn] }))
    for (const id of ['device:a', 'stage:whisper_detect', 'dispatcher', 'voice'])
      expect(node(g, id)?.data.lit, id).toBe(true)
    expect(node(g, 'device:b')?.data.lit).toBe(false)
    expect(edge(g, 'device:a', 'stage:whisper_detect')?.data?.lit).toBe(true)
    expect(edge(g, 'device:b', 'stage:whisper_detect')?.data?.lit).toBe(false)
  })

  it('selected turn wins over the latest one', () => {
    const turns = [makeTurn(2, { device_id: 'b' }), makeTurn(1, { device_id: 'a' })]
    const g = buildGraph(makeState({ turns, selectedTurnId: 1 }))
    expect(node(g, 'device:a')?.data.lit).toBe(true)
    expect(node(g, 'device:b')?.data.lit).toBe(false)
  })

  it('stage without annotations is not lit', () => {
    const g = buildGraph(makeState({ config: config([{ kind: 'whisper_detect' }]), turns: [makeTurn(1, { device_id: 'a' })] }))
    expect(node(g, 'stage:whisper_detect')?.data.lit).toBe(false)
    expect(node(g, 'device:a')?.data.lit).toBe(true)
  })
})
