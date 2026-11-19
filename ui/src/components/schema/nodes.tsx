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
  /** Модель исполнителя загружена в память Ollama. */
  inMemory?: boolean
  /** Блок работает прямо сейчас: короткая подпись под ним («думает…», «calc_add…»). */
  live?: string
  /** Состояние коннектора словами. */
  connectorState?: string
  /** Состояние с ошибкой (коннектор упал). */
  warn?: boolean
}
type SchemaNode = Node<Data>

const CAPTIONS: Record<string, string> = {
  device: 'Колонка',
  stage: 'Обработчик',
  executor: 'Исполнитель',
  voice: 'Голос',
  connector: 'Коннектор',
}

const VOICE_STATES: Record<string, string> = {
  ready: 'готов',
  downloading: 'скачивается',
  failed: 'ошибка',
  missing: 'нет голоса',
}

/** Классы узла: путь выбранного хода (lit), работа сейчас (live), выбор и прочее. */
function classes(type: string, data: Data, selected: boolean): string {
  const cls = ['node', `node-${type}`]
  if (data.lit) cls.push('lit')
  if (data.live) cls.push('live')
  if (data.strong) cls.push('strong')
  if (data.offline) cls.push('offline')
  if (data.enabled === false) cls.push('disabled')
  if (selected) cls.push('picked')
  return cls.join(' ')
}

/** Подпись под работающим блоком (для читалок отметка — в левом списке, без живых областей на схеме). */
function LiveCaption({ text }: { text?: string }) {
  if (!text) return null
  return <div className="node-live">{text}</div>
}

function Card({ type, data, selected }: { type: string; data: Data; selected: boolean }) {
  return (
    <div className={classes(type, data, selected)}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="node-cap">{CAPTIONS[type]}</div>
      <div className="node-title" title={data.label}>
        {data.label}
      </div>
      {data.offline && <div className="node-sub">не в сети</div>}
      {data.enabled === false && <div className="node-sub">выключен</div>}
      {data.voiceState && <div className="node-sub">{VOICE_STATES[data.voiceState] ?? data.voiceState}</div>}
      {data.connectorState && <div className={`node-sub${data.warn ? ' node-warn' : ''}`}>{data.connectorState}</div>}
      <LiveCaption text={data.live} />
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
  return (
    <div className={classes('executor', data, !!selected)}>
      <Handle id="in-top" type="target" position={Position.Top} isConnectable={false} />
      <Handle id="in-left" type="target" position={Position.Left} isConnectable={false} />
      <div className="node-cap">{CAPTIONS.executor}</div>
      <div className="node-title" title={data.label}>
        {data.label}
      </div>
      <div className="node-sub">
        {data.model || '—'}
        {data.inMemory && <span className="node-mem"> · в памяти</span>}
      </div>
      {data.noTools && <div className="node-sub">не умеет передавать</div>}
      {data.unavailable && <div className="node-sub node-warn">модель недоступна</div>}
      <LiveCaption text={data.live} />
      <Handle id="out-right" type="source" position={Position.Right} isConnectable={false} />
      <Handle id="loop-out" type="source" position={Position.Right} style={{ top: '30%' }} isConnectable={false} />
      <Handle id="loop-in" type="target" position={Position.Right} style={{ top: '70%' }} isConnectable={false} />
      <Handle id="out-bottom" type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}

/** Коннектор — компактная карточка: столбец под голосом подписан одним заголовком. */
function Connector({ data, selected }: NodeProps<SchemaNode>) {
  return (
    <div className={classes('connector', data, !!selected)}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="node-row">
        <span className="node-title" title={data.label}>
          {data.label}
        </span>
        {data.connectorState && <span className={`node-sub${data.warn ? ' node-warn' : ''}`}>{data.connectorState}</span>}
        {data.enabled === false && <span className="node-sub">выключен</span>}
      </div>
      <LiveCaption text={data.live} />
    </div>
  )
}

/** Заголовок столбца (не выбирается). */
function Label({ data }: NodeProps<SchemaNode>) {
  return <div className="node-label">{data.label}</div>
}

function Hint({ data }: NodeProps<SchemaNode>) {
  return <div className="node node-hint">{data.label}</div>
}

export const nodeTypes = {
  device: make('device'),
  stage: make('stage'),
  executor: Executor,
  voice: make('voice'),
  connector: Connector,
  label: Label,
  hint: Hint,
}
