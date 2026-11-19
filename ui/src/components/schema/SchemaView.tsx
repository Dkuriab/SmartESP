// Живая схема: колонки → обработчики → исполнители → голос, путь хода подсвечен.
import { Background, BackgroundVariant, ReactFlow } from '@xyflow/react'
import type { Edge, NodeMouseHandler } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import { buildGraph } from '../../schema/buildGraph'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Selection } from '../../state/model'
import { nodeTypes } from './nodes'
import LinkEdge from './LinkEdge'
import Refit from './Refit'

type Props = { state: CoreState; actions: CoreActions }

const edgeTypes = { default: LinkEdge, smoothstep: LinkEdge }

/** Меньше умолчания React Flow (0,5): на узком экране схема в четыре столбца целиком. */
const MIN_ZOOM = 0.2

/** Цвет связи: не на пути — линия, на пути — акцент, через пометку обработчика — фиолетовый. */
function styled(edge: Edge): Edge {
  const { lit, strong, inactive } = (edge.data ?? {}) as { lit?: boolean; strong?: boolean; inactive?: boolean }
  const stroke = strong ? 'var(--purple)' : lit ? 'var(--accent)' : 'var(--line)'
  const style = { stroke, strokeWidth: strong ? 3 : lit ? 2.5 : 1.5, ...(inactive ? { strokeDasharray: '6 4' } : {}) }
  return { ...edge, style }
}

export default function SchemaView({ state, actions }: Props) {
  const graph = useMemo(() => buildGraph(state), [state])
  const { selected } = state
  const nodes = useMemo(
    () => graph.nodes.map((n) => ({
        ...n,
        selected: n.type !== 'hint' && selected?.kind === n.data.kind && selected?.id === n.data.id,
      })),
    [graph, selected],
  )
  const edges = useMemo(() => graph.edges.map(styled), [graph])
  const onClick: NodeMouseHandler = (_, node) => {
    if (node.type === 'hint') return
    actions.select({ kind: node.data.kind, id: node.data.id } as Selection)
  }
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodeClick={onClick}
      fitView
      minZoom={MIN_ZOOM}
      nodesDraggable={false}
      nodesConnectable={false}
      selectNodesOnDrag={false}
      deleteKeyCode={null}
      edgesFocusable={false}
      elementsSelectable
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} color="var(--dot)" gap={22} size={1} />
      <Refit count={nodes.length} />
    </ReactFlow>
  )
}
