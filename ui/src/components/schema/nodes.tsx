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
  model?: string
  /** Модель исполнителя не умеет вызывать инструменты. */
  noTools?: boolean
  /** Модель исполнителя не прогрелась: недоступна. */
  unavailable?: boolean
}
type SchemaNode = Node<Data>

const CAPTIONS: Record<string, string> = {
  device: 'Колонка',
  stage: 'Обработчик',
  executor: 'Исполнитель',
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

function Executor({ data, selected }: NodeProps<SchemaNode>) {
  const cls = ['node', 'node-executor']
  if (data.lit) cls.push('lit')
  if (selected) cls.push('picked')
  return (
    <div className={cls.join(' ')}>
      <Handle id="in-top" type="target" position={Position.Top} isConnectable={false} />
      <Handle id="in-left" type="target" position={Position.Left} isConnectable={false} />
      <div className="node-cap">{CAPTIONS.executor}</div>
      <div className="node-title" title={data.label}>
        {data.label}
      </div>
      <div className="node-sub">{data.model || '—'}</div>
      {data.noTools && <div className="node-sub">не умеет передавать</div>}
      {data.unavailable && <div className="node-sub node-warn">модель недоступна</div>}
      <Handle id="out-right" type="source" position={Position.Right} isConnectable={false} />
      <Handle id="loop-out" type="source" position={Position.Right} style={{ top: '30%' }} isConnectable={false} />
      <Handle id="loop-in" type="target" position={Position.Right} style={{ top: '70%' }} isConnectable={false} />
      <Handle id="out-bottom" type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

function Hint({ data }: NodeProps<SchemaNode>) {
  return <div className="node node-hint">{data.label}</div>
}

export const nodeTypes = {
  device: make('device'),
  stage: make('stage'),
  executor: Executor,
  voice: make('voice'),
  hint: Hint,
}
