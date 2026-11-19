// Построение схемы «колонки → обработчики → исполнители → голос» из данных ядра.
import type { Edge, Node } from '@xyflow/react'
import type { CoreState, Turn } from '../state/model'
import type { ExecutorItem } from './blocks'
import { KNOWN_STAGES, asList, listDevices, listExecutors, voiceLabel } from './blocks'

export type Graph = { nodes: Node[]; edges: Edge[] }

const X_0 = 0
const X_1 = 260
const X_2 = 520
const X_3 = 780
const GAP = 84
const EXEC_GAP = 150
const WHEN_LIMIT = 40
const HINT = 'Колонок пока нет: включите колонку, она появится сама'

function pickTurn(state: CoreState): Turn | undefined {
  const { turns, selectedTurnId } = state
  return turns.find((t) => t.turn_id === selectedTurnId) ?? turns[0]
}

function column(count: number, x: number, i: number, gap = GAP): { x: number; y: number } {
  return { x, y: (i - (count - 1) / 2) * gap }
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
    // включённый обработчик — на пути любого хода; оставил пометку — выделен сильнее
    const data = { label, enabled, lit: enabled && !!turn, strong: enabled && sources.has(kind), kind: 'stage', id: kind }
    nodes.push({ id: `stage:${kind}`, type: 'stage', position: column(kinds.length, X_1, i), data })
  })
  return nodes
}

/** Условие связи для подписи стрелки: не длиннее 40 символов, с «…». */
function shortWhen(when: string): string {
  return when.length > WHEN_LIMIT ? `${when.slice(0, WHEN_LIMIT - 1).trimEnd()}…` : when
}

const execId = (id: string) => `executor:${id}`

/** Путь хода по исполнителям; у старых записей без path — только входной. */
function turnPath(turn: Turn | undefined, entry: ExecutorItem | undefined): string[] {
  if (!turn) return []
  if (turn.path.length > 0) return turn.path
  return entry ? [entry.id] : []
}

/** Подпись связи: условие, а если пусто — описание цели; пусто и там — без подписи. */
function linkText(when: string, target: ExecutorItem | undefined): string {
  return when.trim() !== '' ? when : (target?.description ?? '').trim()
}

/** Параметры стрелки между исполнителями: соседу ниже — сверху вниз, остальным — петля справа. */
function route(from: number, to: number, loops: number): Partial<Edge> {
  if (to === from + 1) return { sourceHandle: 'out-bottom', targetHandle: 'in-top' }
  const offset = 40 + 20 * loops
  return { type: 'smoothstep', sourceHandle: 'loop-out', targetHandle: 'loop-in', pathOptions: { offset } } as Partial<Edge>
}

/** Стрелки исполнитель → исполнитель по связям и от каждого исполнителя к голосу. */
function executorEdges(executors: ExecutorItem[], path: string[]): Edge[] {
  const edges: Edge[] = []
  const last = path[path.length - 1]
  let loops = 0
  executors.forEach((e, from) => {
    const seen = new Set<string>()
    for (const l of e.links) {
      const to = executors.findIndex((x) => x.id === l.to)
      if (to < 0 || l.to === e.id || seen.has(l.to)) continue
      seen.add(l.to)
      const lit = path.some((p, i) => p === e.id && path[i + 1] === l.to)
      const text = linkText(l.when, executors[to])
      const r = route(from, to, loops)
      if (r.type) loops += 1
      edges.push({
        id: `${execId(e.id)}->${execId(l.to)}`,
        source: execId(e.id),
        target: execId(l.to),
        ...r,
        label: text ? shortWhen(text) : undefined,
        data: { lit, strong: false, inactive: !l.active, title: text },
        animated: lit,
      } as Edge)
    }
    const lit = e.id === last
    edges.push({ id: `${execId(e.id)}->voice`, source: execId(e.id), target: 'voice', sourceHandle: 'out-right', data: { lit, strong: false }, animated: lit })
  })
  return edges
}

/**
 * Связи: колонки → включённые обработчики (или сразу входной исполнитель) →
 * исполнители (по связям) → голос. Ход проходит через все включённые обработчики
 * (data.lit); через оставивший пометку — выделенно (data.strong); дальше — по turn.path.
 */
function buildEdges(state: CoreState, configured: string[], executors: ExecutorItem[], path: string[], turn?: Turn): Edge[] {
  const sources = new Set(turn?.annotations.map((a) => a.source))
  const entry = executors[0]?.entry ? executors[0] : undefined
  const edges: Edge[] = []
  const link = (source: string, target: string, lit: boolean, strong = false, targetHandle?: string) =>
    edges.push({ id: `${source}->${target}`, source, target, targetHandle, data: { lit, strong: lit && strong }, animated: lit })
  const head = entry ? execId(entry.id) : undefined
  for (const { device_id: id } of listDevices(state)) {
    const mine = turn?.device_id === id
    if (configured.length === 0 && head) link(`device:${id}`, head, mine, false, 'in-left')
    for (const k of configured) link(`device:${id}`, `stage:${k}`, mine, sources.has(k))
  }
  if (head) for (const k of configured) link(`stage:${k}`, head, !!turn, sources.has(k), 'in-left')
  return [...edges, ...executorEdges(executors, path)]
}

/** Узлы исполнителей: имя, модель, «не умеет передавать» без supports_tools. */
function executorNodes(state: CoreState, executors: ExecutorItem[], path: string[]): Node[] {
  return executors.map((e, i) => {
    const model = state.models?.find((m) => m.name === e.model)
    const data = {
      label: e.name || e.id,
      model: e.model,
      noTools: model !== undefined && !model.supports_tools,
      lit: path.includes(e.id),
      kind: 'executor',
      id: e.id,
    }
    return { id: execId(e.id), type: 'executor', position: column(executors.length, X_2, i, EXEC_GAP), data }
  })
}

/** Чистая функция: узлы и связи схемы, путь выбранного хода подсвечен (data.lit). */
export function buildGraph(state: CoreState): Graph {
  const turn = pickTurn(state)
  const eff = state.config?.effective
  const configured = asList(eff?.stages).map((s) => String(s.kind))
  const kinds = [...configured, ...KNOWN_STAGES.map((k) => k.kind).filter((k) => !configured.includes(k))]
  const executors = listExecutors(state)
  const path = turnPath(turn, executors[0]?.entry ? executors[0] : undefined)
  const nodes = [...leftNodes(state, kinds, configured, turn), ...executorNodes(state, executors, path)]
  nodes.push({ id: 'voice', type: 'voice', position: column(1, X_3, 0), data: { label: voiceLabel(state) ?? '—', voiceState: state.status?.voice?.state, lit: !!turn, kind: 'voice', id: 'voice' } })
  return { nodes, edges: buildEdges(state, configured, executors, path, turn) }
}
