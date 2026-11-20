// Построение схемы «колонки → обработчики → исполнители → голос и коннекторы» из данных ядра.
import type { Edge, Node } from '@xyflow/react'
import type { CoreState, Turn } from '../state/model'
import type { ExecutorItem } from './blocks'
import { KNOWN_STAGES, asList, executorUnavailable, listDevices, listExecutors, modelWithoutTools, voiceLabel } from './blocks'
import { CONNECTOR_STATES, listConnectors, modelInMemory } from './connectors'

export type Graph = { nodes: Node[]; edges: Edge[] }

const X_0 = 0
const X_1 = 260
const X_2 = 520
const X_3 = 780
const GAP = 84
const EXEC_GAP = 150
const WHEN_LIMIT = 40
/** Коннекторы — в столбце голоса, ниже него, под заголовком; компактнее остальных узлов. */
const CONNECTORS_TOP = 110
const CONNECTOR_GAP = 56
/** Подписи живой подсветки исполнителя. */
const EXECUTOR_LIVE = { thinking: 'думает…', speaking: 'говорит' } as const
const HINT = 'Колонок пока нет: включите колонку, она появится сама'

/** Путь показывается только у хода, выбранного в ленте: последний ход сам не подсвечивается. */
function pickTurn(state: CoreState): Turn | undefined {
  const { turns, selectedTurnId } = state
  return selectedTurnId === null ? undefined : turns.find((t) => t.turn_id === selectedTurnId)
}

/** Ключи гаснущей живой подсветки: «executor:<id>», «connector:<id>». */
export type Fading = ReadonlySet<string>
const NONE: Fading = new Set()

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

/**
 * Стрелки исполнитель → исполнитель по связям и от каждого исполнителя к голосу.
 * Связи исполнителя, чья модель не умеет инструменты (noTools), неактивны: пунктир и «неактивна» в title.
 */
function executorEdges(executors: ExecutorItem[], path: string[], noTools: Set<string>): Edge[] {
  const edges: Edge[] = []
  const last = path[path.length - 1]
  let loops = 0
  executors.forEach((e, from) => {
    const seen = new Set<string>()
    const cannot = noTools.has(e.id)
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
        data: { lit, strong: false, inactive: !l.active || cannot, title: cannot ? (text ? `${text} · неактивна` : 'неактивна') : text },
      } as Edge)
    }
    const lit = e.id === last
    edges.push({ id: `${execId(e.id)}->voice`, source: execId(e.id), target: 'voice', sourceHandle: 'out-right', data: { lit, strong: false } })
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
    edges.push({ id: `${source}->${target}`, source, target, targetHandle, data: { lit, strong: lit && strong } })
  const head = entry ? execId(entry.id) : undefined
  for (const { device_id: id } of listDevices(state)) {
    const mine = turn?.device_id === id
    if (configured.length === 0 && head) link(`device:${id}`, head, mine, false, 'in-left')
    for (const k of configured) link(`device:${id}`, `stage:${k}`, mine, sources.has(k))
  }
  if (head) for (const k of configured) link(`stage:${k}`, head, !!turn, sources.has(k), 'in-left')
  const noTools = new Set(executors.filter((e) => modelWithoutTools(state, e.model)).map((e) => e.id))
  return [...edges, ...executorEdges(executors, path, noTools)]
}

/**
 * Узлы исполнителей: имя, модель, «не умеет передавать» без supports_tools, «модель недоступна»
 * после прогрева, «в памяти» — модель загружена в Ollama; live — подпись, если работает сейчас.
 */
function executorNodes(state: CoreState, executors: ExecutorItem[], path: string[], fading: Fading): Node[] {
  return executors.map((e, i) => {
    const now = state.live.executors[e.id]
    const data = {
      label: e.name || e.id,
      model: e.model,
      noTools: modelWithoutTools(state, e.model),
      unavailable: executorUnavailable(state, e.id),
      inMemory: modelInMemory(state, e.model),
      live: now ? EXECUTOR_LIVE[now.state] : undefined,
      fading: fading.has(execId(e.id)),
      lit: path.includes(e.id),
      kind: 'executor',
      id: e.id,
    }
    return { id: execId(e.id), type: 'executor', position: column(executors.length, X_2, i, EXEC_GAP), data }
  })
}

/** Узлы коннекторов под голосом: состояние; инструменты выбранного хода — lit; работающий — live. */
function connectorNodes(state: CoreState, fading: Fading, turn?: Turn): Node[] {
  const used = new Set((turn?.tools ?? []).map((t) => t.connector))
  return listConnectors(state).map((c, i) => {
    const now = state.live.connectors[c.id]
    const data = {
      label: c.name,
      enabled: c.enabled,
      connectorState: c.enabled ? CONNECTOR_STATES[c.state] : undefined,
      warn: c.state === 'failed',
      live: now ? `${now.tool}…` : undefined,
      fading: fading.has(`connector:${c.id}`),
      lit: used.has(c.id),
      kind: 'connector',
      id: c.id,
    }
    return { id: `connector:${c.id}`, type: 'connector', position: { x: X_3, y: CONNECTORS_TOP + i * CONNECTOR_GAP }, data }
  })
}

/** Заголовок столбца коннекторов (если они есть). */
function connectorsHead(count: number): Node[] {
  if (count === 0) return []
  return [{ id: 'connectors', type: 'label', position: { x: X_3, y: CONNECTORS_TOP - 26 }, data: { label: 'Коннекторы', kind: 'label', id: 'connectors' } }]
}

/**
 * Стрелки исполнитель → коннектор: вызовы выбранного хода (lit) и идущие сейчас (live).
 * Постоянных стрелок нет: инструменты есть у всех исполнителей, чья модель их умеет.
 */
function toolEdges(state: CoreState, fading: Fading, turn?: Turn): Edge[] {
  const edges = new Map<string, Edge>()
  const add = (executor: string, connector: string, live: boolean) => {
    if (!executor || !connector) return
    const id = `${execId(executor)}->connector:${connector}`
    const data = { lit: true, strong: false, live, fading: live && fading.has(`connector:${connector}`) }
    edges.set(id, { id, source: execId(executor), target: `connector:${connector}`, sourceHandle: 'out-right', data, animated: live })
  }
  for (const t of turn?.tools ?? []) add(t.executor, t.connector, false)
  for (const [connector, now] of Object.entries(state.live.connectors)) add(now.executor, connector, true)
  const known = new Set([...listExecutors(state).map((e) => execId(e.id)), ...listConnectors(state).map((c) => `connector:${c.id}`)])
  return [...edges.values()].filter((e) => known.has(e.source) && known.has(e.target))
}

/**
 * Чистая функция: узлы и связи схемы, путь выбранного хода подсвечен (data.lit), работающее
 * сейчас — data.live; fading — живая подсветка, которая уже гаснет (data.fading).
 */
export function buildGraph(state: CoreState, fading: Fading = NONE): Graph {
  const turn = pickTurn(state)
  const eff = state.config?.effective
  const configured = asList(eff?.stages).map((s) => String(s.kind))
  const kinds = [...configured, ...KNOWN_STAGES.map((k) => k.kind).filter((k) => !configured.includes(k))]
  const executors = listExecutors(state)
  const path = turnPath(turn, executors[0]?.entry ? executors[0] : undefined)
  const nodes = [...leftNodes(state, kinds, configured, turn), ...executorNodes(state, executors, path, fading)]
  nodes.push({ id: 'voice', type: 'voice', position: column(1, X_3, 0), data: { label: voiceLabel(state) ?? '—', voiceState: state.status?.voice?.state, lit: !!turn, kind: 'voice', id: 'voice' } })
  const connectors = connectorNodes(state, fading, turn)
  nodes.push(...connectorsHead(connectors.length), ...connectors)
  return { nodes, edges: [...buildEdges(state, configured, executors, path, turn), ...toolEdges(state, fading, turn)] }
}
