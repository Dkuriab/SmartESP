// Стрелка между исполнителями: подпись с полным условием во всплывающей подсказке.
import { BaseEdge, EdgeLabelRenderer, getBezierPath, getSmoothStepPath } from '@xyflow/react'
import type { EdgeProps } from '@xyflow/react'
import './schema.css'

type Data = { title?: string }

/** Подпись на середине стрелки; полный текст — в title. */
export function EdgeLabel({ text, title, x, y }: { text: string; title?: string; x: number; y: number }) {
  return (
    <span
      className="edge-label nodrag nopan"
      title={title}
      style={{ position: 'absolute', pointerEvents: 'all', transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
    >
      {text}
    </span>
  )
}

export default function LinkEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, label, style, data } = props
  const loop = props.type === 'smoothstep'
  const offset = (props as { pathOptions?: { offset?: number } }).pathOptions?.offset
  const geo = { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition }
  const [path, x, y] = loop ? getSmoothStepPath({ ...geo, offset }) : getBezierPath(geo)
  return (
    <>
      <BaseEdge id={props.id} path={path} style={style} />
      {typeof label === 'string' && label !== '' && (
        <EdgeLabelRenderer>
          <EdgeLabel text={label} title={(data as Data | undefined)?.title} x={x} y={y} />
        </EdgeLabelRenderer>
      )}
    </>
  )
}
