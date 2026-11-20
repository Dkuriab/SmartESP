// Настройки коннектора (MCP): включить или выключить, состояние, инструменты, ошибка,
// объявленные им настройки (форма) и остальное окружение (только показ).
import type { ReactElement } from 'react'
import { isApplying } from '../../schema/blocks'
import type { ConnectorItem } from '../../schema/connectors'
import { CONNECTOR_STATES, connectorToggle, connectorsLocked, listConnectors } from '../../schema/connectors'
import type { CoreActions } from '../../state/actions'
import type { ConnectorSetting, CoreState } from '../../state/model'
import ConnectorForm from './ConnectorForm'

type Props = {
  connector: ConnectorItem
  applying: boolean
  /** Переключать нельзя (применяется или настройки не загружены). */
  locked: boolean
  /** Вызов идёт прямо сейчас: имя инструмента. */
  liveTool?: string
  onToggle: (on: boolean) => void
  /** Настройки, объявленные коннектором (smartesp.json); их можно менять здесь. */
  settings?: ConnectorSetting[]
  /** Сохранить изменённые настройки; ответ — текст ошибки ('' — принято). */
  onSave?: (env: Record<string, string>) => Promise<string>
}

const NO_SETTINGS: ConnectorSetting[] = []
const noSave = () => Promise.resolve('')

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
      <p className="set-text">Эти значения меняются в config.yaml (раздел connectors).</p>
    </>
  )
}

export default function ConnectorSettings(props: Props) {
  const { connector, applying, locked, liveTool, onToggle, settings = NO_SETTINGS, onSave = noSave } = props
  const declared = new Set(settings.map((s) => s.key))
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
      {settings.length > 0 && (
        // новые значения из ядра (после применения) — форма заново
        <ConnectorForm key={JSON.stringify(settings)} settings={settings} disabled={locked} onSave={onSave} />
      )}
      <Env env={connector.env.filter((e) => !declared.has(e.key))} />
    </div>
  )
}

type PanelProps = { state: CoreState; actions: CoreActions; id: string; hint: ReactElement }

/** Панель коннектора id из состояния; неизвестный — подсказка. */
export function ConnectorPanel({ state, actions, id, hint }: PanelProps) {
  const connector = listConnectors(state).find((c) => c.id === id)
  if (!connector) return hint
  const onToggle = (on: boolean) =>
    void actions.setConnectors(connectorToggle(id, on), `${connector.name}: ${on ? 'включён' : 'выключен'}`)
  const settings = state.connectors?.find((c) => c.id === id)?.settings
  const onSave = (env: Record<string, string>) => actions.saveConnectorEnv(id, env, `${connector.name}: настройки`)
  return (
    <ConnectorSettings
      connector={connector}
      applying={isApplying(state)}
      locked={connectorsLocked(state)}
      liveTool={state.live.connectors[id]?.tool}
      onToggle={onToggle}
      settings={settings}
      onSave={onSave}
    />
  )
}
