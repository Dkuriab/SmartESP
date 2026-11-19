// Свои узлы схемы в стиле панелей наброска.
import { Handle, Position } from '@xyflow/react'
import type { Node, NodeProps } from '@xyflow/react'
import './schema.css'

type Data = {
  label: string
  lit?: boolean
  /** Обработчик оставил пометку в выбранном ходе. */
  strong?: boolean
  offline?: boolean
  enabled?: boolean
  voiceState?: string
}
type SchemaNode = Node<Data>

const CAPTIONS: Record<string, string> = {
  device: 'Колонка',
  stage: 'Обработчик',
  dispatcher: 'Диспетчер',
  voice: 'Голос',
}

const VOICE_STATES: Record<string, string> = {
  ready: 'готов',
  downloading: 'скачивается',
  failed: 'ошибка',
  missing: 'нет голоса',
}

function Card({ type, data, selected }: { type: string; data: Data; selected: boolean }) {
  const cls = ['node', `node-${type}`]
  if (data.lit) cls.push('lit')
  if (data.strong) cls.push('strong')
  if (data.offline) cls.push('offline')
  if (data.enabled === false) cls.push('disabled')
  if (selected) cls.push('picked')
  return (
    <div className={cls.join(' ')}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="node-cap">{CAPTIONS[type]}</div>
      <div className="node-title" title={data.label}>
        {data.label}
      </div>
      {data.offline && <div className="node-sub">не в сети</div>}
      {data.enabled === false && <div className="node-sub">выключен</div>}
      {data.voiceState && <div className="node-sub">{VOICE_STATES[data.voiceState] ?? data.voiceState}</div>}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}

function make(type: string) {
  return function SchemaCard({ data, selected }: NodeProps<SchemaNode>) {
    return <Card type={type} data={data} selected={!!selected} />
  }
}

function Hint({ data }: NodeProps<SchemaNode>) {
  return <div className="node node-hint">{data.label}</div>
}

export const nodeTypes = {
  device: make('device'),
  stage: make('stage'),
  dispatcher: make('dispatcher'),
  voice: make('voice'),
  hint: Hint,
}
