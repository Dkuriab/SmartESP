// Верхние панели: вкладки «Схема» и «Лента» по центру, состояние справа.
import type { CoreState } from '../../state/model'
import StatusPill from './StatusPill'
import './top.css'

export type Tab = 'schema' | 'feed'
type Props = { state: CoreState; tab: Tab; onTab: (tab: Tab) => void }

const CORE_TEXT = { warming: 'прогревается', ready: 'работает', stopping: 'останавливается' }
const TABS: Array<[Tab, string]> = [
  ['schema', 'Схема'],
  ['feed', 'Лента'],
]

function Status({ state }: { state: CoreState }) {
  const { status, connection } = state
  if (connection === 'offline') return <StatusPill text="Нет связи с ядром" tone="bad" />
  if (!status) return <StatusPill text="Подключение…" tone="off" />
  const online = status.devices.filter((d) => d.connected).length
  return (
    <>
      <StatusPill text={`Ядро: ${CORE_TEXT[status.state]}`} tone={status.state === 'ready' ? 'ok' : 'warn'} />
      <StatusPill text={status.ollama.reachable ? 'Ollama ✓' : 'Ollama ✗'} tone={status.ollama.reachable ? 'ok' : 'bad'} />
      <StatusPill text={`Колонки ${online} из ${status.devices.length}`} tone="off" />
    </>
  )
}

export default function TopBar({ state, tab, onTab }: Props) {
  return (
    <>
      <div className="panel top-tabs" role="tablist">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={`seg${tab === id ? ' on' : ''}`}
            onClick={() => onTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="panel top-status">
        <Status state={state} />
      </div>
    </>
  )
}
