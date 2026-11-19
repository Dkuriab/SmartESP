// Стрелка между исполнителями: подпись с полным условием во всплывающей подсказке.
import { BaseEdge, getBezierPath, getSmoothStepPath } from '@xyflow/react'
import type { EdgeProps } from '@xyflow/react'
import './schema.css'

const LABEL_W = 280
const LABEL_H = 24

type Data = { title?: string }

export default function LinkEdge(props: EdgeProps) {
  const { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, label, style, data } = props
  const loop = props.type === 'smoothstep'
  const offset = (props as { pathOptions?: { offset?: number } }).pathOptions?.offset
  const geo = { sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition }
  const [path, x, y] = loop ? getSmoothStepPath({ ...geo, offset }) : getBezierPath(geo)
  const title = (data as Data | undefined)?.title
  return (
    <>
      <BaseEdge id={props.id} path={path} style={style} />
      {label && (
        <foreignObject className="edge-label-box" x={x - LABEL_W / 2} y={y - LABEL_H / 2} width={LABEL_W} height={LABEL_H}>
          <span className="edge-label" title={title}>
            {label}
          </span>
        </foreignObject>
      )}
    </>
  )
}
