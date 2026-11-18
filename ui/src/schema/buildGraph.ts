// Построение схемы «колонки → обработчики → диспетчер → голос» из данных ядра.
import type { Edge, Node } from '@xyflow/react'
import type { CoreState, Turn } from '../state/model'

/** Известные обработчики: выключенный показывается серым и без связей. */
export const KNOWN_STAGES = [{ kind: 'whisper_detect', title: 'Шёпот' }]

export type Graph = { nodes: Node[]; edges: Edge[] }

const [X_0, X_1, X_2, X_3] = [0, 260, 520, 780] as [number, number, number, number]
const GAP = 84
const HINT = 'Колонок пока нет: включите колонку, она появится сама'

function asList(v: unknown): Record<string, unknown>[] {
  return Array.isArray(v) ? v.filter((e): e is Record<string, unknown> => typeof e === 'object' && e !== null) : []
}

/** Колонки: из status, плюс известные только настройкам (ни разу не подключались). */
function devicesOf(state: CoreState): { id: string; name: string; connected: boolean }[] {
  const list = (state.status?.devices ?? []).map((d) => ({ id: d.device_id, name: d.name, connected: d.connected }))
  const cfg = state.config?.effective.devices
  if (cfg && typeof cfg === 'object' && !Array.isArray(cfg)) {
    for (const [id, v] of Object.entries(cfg)) {
      if (list.some((d) => d.id === id)) continue
      const name = (v as { name?: unknown } | null)?.name
      list.push({ id, name: typeof name === 'string' ? name : '', connected: false })
    }
  }
  return list
}

function pickTurn(state: CoreState): Turn | undefined {
  const { turns, selectedTurnId } = state
  return turns.find((t) => t.turn_id === selectedTurnId) ?? turns[0]
}

function column(count: number, x: number, i: number): { x: number; y: number } {
  return { x, y: (i - (count - 1) / 2) * GAP }
}

function voiceLabel(state: CoreState): string {
  const live = state.status?.voice
  const tts = state.config?.effective.tts as { kind?: unknown; voice?: unknown } | undefined
  const kind = live?.kind ?? tts?.kind
  const voice = live?.kind ? live.voice : tts?.voice
  return kind ? `${String(kind)} · ${String(voice ?? '')}` : '—'
}

function dispatcherLabel(executors: unknown): string {
  const entry = asList(executors).find((e) => e.entry === true)
  return typeof entry?.model === 'string' ? entry.model : '—'
}

/** Узлы колонок (или подсказка) и обработчиков. */
function leftNodes(state: CoreState, kinds: string[], configured: string[], turn?: Turn): Node[] {
  const devices = devicesOf(state)
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
  for (const d of devicesOf(state)) {
    const mine = turn?.device_id === d.id
    if (configured.length === 0) link(`device:${d.id}`, 'dispatcher', mine)
    for (const k of configured) link(`device:${d.id}`, `stage:${k}`, mine && sources.has(k))
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
    { id: 'dispatcher', type: 'dispatcher', position: column(1, X_2, 0), data: { label: dispatcherLabel(eff?.executors), lit, kind: 'dispatcher', id: 'dispatcher' } },
    { id: 'voice', type: 'voice', position: column(1, X_3, 0), data: { label: voiceLabel(state), voiceState: state.status?.voice?.state, lit, kind: 'voice', id: 'voice' } },
  )
  return { nodes, edges: buildEdges(state, configured, turn) }
}
