// Построение схемы «колонки → обработчики → диспетчер → голос» из данных ядра.
import type { Edge, Node } from '@xyflow/react'
import type { CoreState, Turn } from '../state/model'
import { KNOWN_STAGES, asList, dispatcherInfo, listDevices, voiceLabel } from './blocks'

export type Graph = { nodes: Node[]; edges: Edge[] }

const X_0 = 0
const X_1 = 260
const X_2 = 520
const X_3 = 780
const GAP = 84
const HINT = 'Колонок пока нет: включите колонку, она появится сама'

function pickTurn(state: CoreState): Turn | undefined {
  const { turns, selectedTurnId } = state
  return turns.find((t) => t.turn_id === selectedTurnId) ?? turns[0]
}

function column(count: number, x: number, i: number): { x: number; y: number } {
  return { x, y: (i - (count - 1) / 2) * GAP }
}

/** Узлы колонок (или подсказка) и обработчиков. */
function leftNodes(state: CoreState, kinds: string[], configured: string[], turn?: Turn): Node[] {
  const devices = listDevices(state).map((d) => ({ id: d.device_id, name: d.name, connected: d.connected }))
  const sources = new Set(turn?.annotations.map((a) => a.source))
  const nodes: Node[] = []
  if (devices.length === 0) {
    nodes.push({ id: 'hint', type: 'hint', position: column(1, X_0, 0), data: { label: HINT } })
  }
  devices.forEach((d, i) => {
    const data = { label: d.name || d.id, offline: !d.connected, lit: turn?.device_id === d.id, kind: 'device', id: d.id }
    nodes.push({ id: `device:${d.id}`, type: 'device', position: column(devices.length, X_0, i), data })
  })
  kinds.forEach((kind, i) => {
    const enabled = configured.includes(kind)
    const label = KNOWN_STAGES.find((k) => k.kind === kind)?.title ?? kind
    const data = { label, enabled, lit: enabled && sources.has(kind), kind: 'stage', id: kind }
    nodes.push({ id: `stage:${kind}`, type: 'stage', position: column(kinds.length, X_1, i), data })
  })
  return nodes
}

/** Связи: колонки → включённые обработчики (или сразу диспетчер) → диспетчер → голос. */
function buildEdges(state: CoreState, configured: string[], turn?: Turn): Edge[] {
  const sources = new Set(turn?.annotations.map((a) => a.source))
  const edges: Edge[] = []
  const link = (source: string, target: string, lit: boolean) =>
    edges.push({ id: `${source}->${target}`, source, target, data: { lit }, animated: lit })
  for (const { device_id: id } of listDevices(state)) {
    const mine = turn?.device_id === id
    if (configured.length === 0) link(`device:${id}`, 'dispatcher', mine)
    for (const k of configured) link(`device:${id}`, `stage:${k}`, mine && sources.has(k))
  }
  for (const k of configured) link(`stage:${k}`, 'dispatcher', sources.has(k))
  link('dispatcher', 'voice', !!turn)
  return edges
}

/** Чистая функция: узлы и связи схемы, путь выбранного хода подсвечен (data.lit). */
export function buildGraph(state: CoreState): Graph {
  const turn = pickTurn(state)
  const eff = state.config?.effective
  const configured = asList(eff?.stages).map((s) => String(s.kind))
  const kinds = [...configured, ...KNOWN_STAGES.map((k) => k.kind).filter((k) => !configured.includes(k))]
  const lit = !!turn
  const nodes = leftNodes(state, kinds, configured, turn)
  nodes.push(
    { id: 'dispatcher', type: 'dispatcher', position: column(1, X_2, 0), data: { label: dispatcherInfo(state)?.model || '—', lit, kind: 'dispatcher', id: 'dispatcher' } },
    { id: 'voice', type: 'voice', position: column(1, X_3, 0), data: { label: voiceLabel(state) ?? '—', voiceState: state.status?.voice?.state, lit, kind: 'voice', id: 'voice' } },
  )
  return { nodes, edges: buildEdges(state, configured, turn) }
}
