// Живая схема: колонки → обработчики → диспетчер → голос, путь хода подсвечен.
import { Background, BackgroundVariant, ReactFlow } from '@xyflow/react'
import type { Edge, NodeMouseHandler } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo } from 'react'
import { buildGraph } from '../../schema/buildGraph'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Selection } from '../../state/model'
import { nodeTypes } from './nodes'

type Props = { state: CoreState; actions: CoreActions }

function styled(edge: Edge): Edge {
  const lit = (edge.data as { lit?: boolean } | undefined)?.lit
  return { ...edge, style: { stroke: lit ? 'var(--accent)' : 'var(--line)', strokeWidth: lit ? 2.5 : 1.5 } }
}

export default function SchemaView({ state, actions }: Props) {
  const graph = useMemo(() => buildGraph(state), [state])
  const { selected } = state
  const nodes = useMemo(
    () => graph.nodes.map((n) => ({ ...n, selected: selected?.kind === n.data.kind && selected?.id === n.data.id })),
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
      onNodeClick={onClick}
      fitView
      nodesDraggable={false}
      nodesConnectable={false}
      edgesFocusable={false}
      elementsSelectable
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} color="var(--dot)" gap={22} size={1} />
    </ReactFlow>
  )
}
