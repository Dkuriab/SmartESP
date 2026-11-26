// Настройки коннектора (MCP): включить или выключить, состояние, инструменты, ошибка,
// объявленные им настройки (форма) и остальное окружение (только показ).
import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { isApplying } from '../../schema/blocks'
import type { ConnectorItem } from '../../schema/connectors'
import { CONNECTOR_STATES, connectorToggle, connectorsLocked, listConnectors, withPair } from '../../schema/connectors'
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
  /** Пояснение коннектора и пример для config.yaml (только показ). */
  note?: { text: string; example: string }
  /** Устройства ввода Mac — для настроек audio_input (запрашиваются при открытии панели). */
  loadInputs?: () => Promise<string[]>
}

const NO_SETTINGS: ConnectorSetting[] = []
const noSave = () => Promise.resolve('')

/** Пояснение коннектора (например, почему настроек в приложении нет) и пример для config.yaml. */
function Note({ text, example }: { text: string; example: string }) {
  if (!text && !example) return null
  return (
    <>
      {text && <p className="set-text">{text}</p>}
      {example && <pre className="config-example">{example}</pre>}
    </>
  )
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
      <p className="set-text">Эти значения меняются в config.yaml (раздел connectors).</p>
    </>
  )
}

type ClientProps = { connector: ConnectorItem; settings: ConnectorSetting[]; locked: boolean; onSave: (env: Record<string, string>) => Promise<string> }

/** Клиент ядра (бот): кто ему написал — «Добавить» в список; последние строки журнала. */
function ClientParts({ connector, settings, locked, onSave }: ClientProps) {
  const add = (key: string, value: string) => {
    const current = settings.find((s) => s.key === key)?.value ?? ''
    void onSave({ [key]: withPair(current, value) })
  }
  return (
    <>
      {connector.suggestions.length > 0 && <div className="cap set-label">Написали боту</div>}
      {connector.suggestions.map((s) => (
        <div key={s.value} className="field">
          <span className="val-text" title={s.value}>{s.text}</span>
          <button type="button" className="btn" disabled={locked} onClick={() => add(s.key, s.value)}>Добавить</button>
        </div>
      ))}
      <details className="job-log" open={connector.state === 'failed'}>
        <summary className="cap">{`Журнал (${connector.log.length})`}</summary>
        <pre className="client-log">{connector.log.slice(-60).join('\n') || 'пусто'}</pre>
      </details>
    </>
  )
}

const NO_INPUTS: string[] = []

/** Устройства ввода Mac, если среди настроек есть выбор устройства; иначе ничего не запрашиваем. */
function useInputs(settings: ConnectorSetting[], load?: () => Promise<string[]>): string[] {
  const [inputs, setInputs] = useState(NO_INPUTS)
  const wanted = settings.some((s) => s.type === 'audio_input')
  useEffect(() => {
    if (!wanted || !load) return
    let alive = true
    void load().then((list) => alive && setInputs(list))
    return () => {
      alive = false
    }
  }, [wanted, load])
  return inputs
}

export default function ConnectorSettings(props: Props) {
  const { connector, applying, locked, liveTool, onToggle, settings = NO_SETTINGS, onSave = noSave, note } = props
  const inputs = useInputs(settings, props.loadInputs)
  const declared = new Set(settings.map((s) => s.key))
  const client = connector.kind === 'client'
  return (
    <div className="set">
      <h3 className="set-title cut">{client ? '💬' : '🧩'} {connector.name}</h3>
      <div className="set-sub">{client ? 'Клиент ядра' : 'Коннектор'} · {connector.id}</div>
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
      {client && <ClientParts connector={connector} settings={settings} locked={locked} onSave={onSave} />}
      {!client && <div className="cap set-label">Инструменты</div>}
      {client ? null : connector.tools.length > 0 ? (
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
        <ConnectorForm key={JSON.stringify(settings)} settings={settings} disabled={locked} onSave={onSave} inputs={inputs} />
      )}
      {note && <Note text={note.text} example={note.example} />}
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
  const detail = state.connectors?.find((c) => c.id === id)
  const onSave = (env: Record<string, string>) => actions.saveConnectorEnv(id, env, `${connector.name}: настройки`)
  return (
    <ConnectorSettings
      connector={connector}
      applying={isApplying(state)}
      locked={connectorsLocked(state)}
      liveTool={state.live.connectors[id]?.tool}
      onToggle={onToggle}
      settings={detail?.settings}
      onSave={onSave}
      note={detail && { text: detail.note ?? '', example: detail.example ?? '' }}
      loadInputs={actions.loadAudioInputs}
    />
  )
}
