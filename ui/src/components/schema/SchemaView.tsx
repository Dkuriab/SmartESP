// Живая схема: колонки → обработчики → исполнители → голос и коннекторы. Путь выбранного
// в ленте хода — синий; работающее сейчас — зелёное, держится и плавно гаснет.
// Фон — общий холст интерфейса (своего поля у схемы нет); узлы перетаскиваются.
import { ReactFlow } from '@xyflow/react'
import type { Edge, Node, NodeMouseHandler } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import { buildGraph } from '../../schema/buildGraph'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Selection } from '../../state/model'
import { nodeTypes } from './nodes'
import LinkEdge from './LinkEdge'
import Refit from './Refit'
import { useBoxSize } from './useBoxSize'
import { useLiveGlow } from './useLiveGlow'
import { useSchemaNodes } from './useSchemaNodes'

type Props = { state: CoreState; actions: CoreActions }

const edgeTypes = { default: LinkEdge, smoothstep: LinkEdge }

/** Меньше умолчания React Flow (0,5): на узком экране схема в четыре столбца целиком. */
const MIN_ZOOM = 0.2
/** Узлы-подписи: не выбираются и не перетаскиваются. */
const PASSIVE = new Set(['hint', 'label'])

type EdgeFlags = { lit?: boolean; strong?: boolean; inactive?: boolean; live?: boolean; fading?: boolean }

/**
 * Цвет связи: не на пути — линия, на пути — акцент, через пометку обработчика — фиолетовый,
 * идущий сейчас вызов инструмента — зелёный (гаснущий — с классом fading).
 */
function styled(edge: Edge): Edge {
  const { lit, strong, inactive, live, fading } = (edge.data ?? {}) as EdgeFlags
  const stroke = live ? 'var(--green)' : strong ? 'var(--purple)' : lit ? 'var(--accent)' : 'var(--line)'
  const style = { stroke, strokeWidth: strong || live ? 3 : lit ? 2.5 : 1.5, ...(inactive ? { strokeDasharray: '6 4' } : {}) }
  return { ...edge, style, className: fading ? 'fading' : live ? 'live' : undefined }
}

/** Выбранный блок отмечен; подписи не выбираются и не тянутся. */
function marked(node: Node, selected: Selection | null): Node {
  const passive = PASSIVE.has(node.type ?? '')
  return { ...node, draggable: !passive, selected: !passive && selected?.kind === node.data.kind && selected?.id === node.data.id }
}

export default function SchemaView({ state, actions }: Props) {
  const glow = useLiveGlow(state.live, state.connection === 'online')
  const graph = useMemo(() => buildGraph({ ...state, live: glow.live }, glow.fading), [state, glow])
  const { nodes, onNodesChange, reset } = useSchemaNodes(graph.nodes)
  const [box, setBox] = useState<HTMLDivElement | null>(null)
  const size = useBoxSize(box)
  const [resets, setResets] = useState(0)
  const { selected } = state
  const shown = useMemo(() => nodes.map((n) => marked(n, selected)), [nodes, selected])
  const edges = useMemo(() => graph.edges.map(styled), [graph])
  const onClick: NodeMouseHandler = (_, node) => {
    if (PASSIVE.has(node.type ?? '')) return
    actions.select({ kind: node.data.kind, id: node.data.id } as Selection)
  }
  const relayout = () => {
    reset()
    setResets((n) => n + 1)
  }
  return (
    <div className="schema-flow" ref={setBox}>
      <ReactFlow
        nodes={shown}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={onClick}
        minZoom={MIN_ZOOM}
        nodesConnectable={false}
        selectNodesOnDrag={false}
        deleteKeyCode={null}
        edgesFocusable={false}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
      >
        <Refit fitKey={`${nodes.length}:${resets}`} width={size.width} height={size.height} />
      </ReactFlow>
      {/* своя кнопка, не Panel React Flow: его классы top/left совпали бы с панелями каркаса */}
      <button type="button" className="schema-reset" onClick={relayout} title="Вернуть узлы на места по умолчанию">
        Расставить заново
      </button>
    </div>
  )
}
