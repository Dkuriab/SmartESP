// Верхние панели: вкладки «Схема» и «Лента» по центру, состояние справа;
// на узком экране — ещё кнопки «Список» и «Настройки».
import type { CoreState } from '../../state/model'
import StatusPill from './StatusPill'
import './top.css'

export type Tab = 'schema' | 'feed'
/** Боковая панель, открытая поверх схемы на узком экране. */
export type Overlay = 'list' | 'settings'
type Props = {
  state: CoreState
  tab: Tab
  onTab: (tab: Tab) => void
  /** Открытая панель (null — никакой); не передан — кнопок панелей нет. */
  overlay?: Overlay | null
  onOverlay?: (overlay: Overlay | null) => void
}

const OVERLAYS: Array<[Overlay, string]> = [
  ['list', 'Список'],
  ['settings', 'Настройки'],
]

/** Кнопки панелей: видны только на узком экране (см. top.css); повторное нажатие закрывает. */
function OverlayToggles({ overlay, onOverlay }: { overlay: Overlay | null; onOverlay: (o: Overlay | null) => void }) {
  return (
    <div className="panel top-toggles">
      {OVERLAYS.map(([id, label]) => (
        <button
          key={id}
          type="button"
          aria-pressed={overlay === id}
          className={`seg${overlay === id ? ' on' : ''}`}
          onClick={() => onOverlay(overlay === id ? null : id)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

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

export default function TopBar({ state, tab, onTab, overlay, onOverlay }: Props) {
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
      {overlay !== undefined && onOverlay && <OverlayToggles overlay={overlay} onOverlay={onOverlay} />}
      <div className="panel top-status">
        <Status state={state} />
      </div>
    </>
  )
}
