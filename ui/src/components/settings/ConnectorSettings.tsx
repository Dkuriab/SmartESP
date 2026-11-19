// Настройки коннектора (MCP): включить или выключить, состояние, инструменты, ошибка, окружение.
import type { ConnectorItem } from '../../schema/connectors'
import { CONNECTOR_STATES } from '../../schema/connectors'

type Props = {
  connector: ConnectorItem
  applying: boolean
  /** Переключать нельзя (применяется или настройки не загружены). */
  locked: boolean
  /** Вызов идёт прямо сейчас: имя инструмента. */
  liveTool?: string
  onToggle: (on: boolean) => void
}

function Env({ env }: { env: ConnectorItem['env'] }) {
  if (env.length === 0) return null
  return (
    <>
      <div className="cap set-label">Окружение</div>
      {env.map(({ key, value }) => (
        <div key={key} className="field">
          <span className="lbl" title={key}>{key}</span>
          <span className="val-text" title={value}>{value || 'не задано'}</span>
        </div>
      ))}
      <p className="set-text">Значения меняются в config.yaml (раздел connectors).</p>
    </>
  )
}

export default function ConnectorSettings({ connector, applying, locked, liveTool, onToggle }: Props) {
  return (
    <div className="set">
      <h3 className="set-title cut">🧩 {connector.name}</h3>
      <div className="set-sub">Коннектор · {connector.id}</div>
      <label className="field">
        <span className="lbl">Включён</span>
        <input
          type="checkbox"
          role="switch"
          className="switch"
          checked={connector.enabled}
          disabled={locked}
          onChange={(e) => onToggle(e.target.checked)}
        />
      </label>
      {applying && <div className="set-note">Применяется…</div>}
      <div className="field">
        <span className="lbl">Состояние</span>
        <span className="val-text">{liveTool ? `работает: ${liveTool}` : CONNECTOR_STATES[connector.state]}</span>
      </div>
      {connector.error && <div className="set-note bad">{connector.error}</div>}
      <div className="cap set-label">Инструменты</div>
      {connector.tools.length > 0 ? (
        <div className="set-tools">
          {connector.tools.map((t) => (
            <span key={t} className={`set-tool${t === liveTool ? ' live' : ''}`}>{t}</span>
          ))}
        </div>
      ) : (
        <p className="set-text">{connector.state === 'ready' ? 'Нет инструментов' : 'Появятся, когда коннектор запустится'}</p>
      )}
      <Env env={connector.env} />
    </div>
  )
}
