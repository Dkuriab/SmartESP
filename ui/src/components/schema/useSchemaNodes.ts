// Узлы схемы в состоянии компонента: перетаскиваются, места запоминаются в браузере,
// свежие данные ядра (опрос раз в 5 с, события) не сбрасывают ни места, ни размеры.
import { NodeChangeset } from '@xyflow/react'
import type { Node, OnNodesChange } from '@xyflow/react'
import { useState } from 'react'
import { browserStorage, clearPositions, finishedMoves, loadPositions, mergeNodes, savePositions } from '../../schema/layout'

export type SchemaNodes = {
  nodes: Node[]
  onNodesChange: OnNodesChange
  /** «Расставить заново»: забыть места, вернуть вычисленные. */
  reset: () => void
}

/** Нам нужны только сдвиги и размеры; выбор ведёт состояние интерфейса, удалять нечего. */
const OWN = new Set(['position', 'dimensions'])

export function useSchemaNodes(next: Node[]): SchemaNodes {
  const [storage] = useState(browserStorage)
  const [saved, setSaved] = useState(() => loadPositions(storage))
  const [nodes, setNodes] = useState(() => mergeNodes([], next, saved))
  const [source, setSource] = useState(next)
  if (source !== next) {
    // новые данные — сразу в этот же рендер, без кадра со старыми узлами
    setSource(next)
    setNodes(mergeNodes(nodes, next, saved))
  }
  const onNodesChange: OnNodesChange = (changes) => {
    const own = changes.toArray().filter((c) => OWN.has(c.type))
    if (own.length === 0) return
    setNodes((current) => new NodeChangeset(own).applyTo(current))
    const moved = finishedMoves(saved, own)
    if (!moved) return
    savePositions(storage, moved)
    setSaved(moved)
  }
  const reset = () => {
    clearPositions(storage)
    setSaved({})
    setNodes(mergeNodes(nodes.map((n) => ({ ...n, dragging: false })), next, {}))
  }
  return { nodes, onNodesChange, reset }
}
