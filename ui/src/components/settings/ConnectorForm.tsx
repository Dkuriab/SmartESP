// Форма настроек, объявленных коннектором: поля по типам, сохранение одной правкой.
import { useState } from 'react'
import type { ConnectorSetting } from '../../state/model'
import type { FolderRow } from './connectorValues'
import { changedEnv, formatFolders, initialValue, parseFolders, valueError } from './connectorValues'
import FolderList from './FolderList'

type Props = {
  settings: ConnectorSetting[]
  /** Менять нельзя: правка применяется или настройки не загружены. */
  disabled: boolean
  /** Сохранить изменённые значения; ответ — текст ошибки ('' — принято). */
  onSave: (env: Record<string, string>) => Promise<string>
}

type FieldProps = { setting: ConnectorSetting; value: string; disabled: boolean; onChange: (v: string) => void }

/** Подсказка в пустом поле: заданный секрет не показывается — вводят новый. */
function placeholderOf(setting: ConnectorSetting): string {
  if (setting.type === 'secret') return setting.value ? 'задано — введите новое' : 'не задано'
  return setting.type === 'path' ? '/Users/…' : ''
}

/** Поле одной настройки: флаг — переключатель, секрет — скрытый ввод, остальное — строка. */
function SettingField({ setting, value, disabled, onChange }: FieldProps) {
  if (setting.type === 'flag') {
    return (
      <label className="field">
        <span className="lbl">{setting.title}</span>
        <input
          type="checkbox"
          role="switch"
          className="switch"
          checked={value === '1'}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? '1' : '')}
        />
      </label>
    )
  }
  return (
    <label className="field field-block">
      <span className="lbl">{setting.title}</span>
      <input
        className="val wide"
        type={setting.type === 'secret' ? 'password' : 'text'}
        autoComplete="off"
        spellCheck={false}
        placeholder={placeholderOf(setting)}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

type RowProps = {
  setting: ConnectorSetting
  values: Record<string, string>
  lists: Record<string, FolderRow[]>
  disabled: boolean
  onValue: (key: string, value: string) => void
  onRows: (key: string, rows: FolderRow[]) => void
}

/** Строка формы: поле по типу настройки и подсказка под ним. */
function SettingRow({ setting: s, values, lists, disabled, onValue, onRows }: RowProps) {
  return (
    <div className="setting">
      {s.type === 'list' ? (
        <div className="field field-block">
          <span className="lbl">{s.title}</span>
          <FolderList title={s.title} rows={lists[s.key] ?? []} disabled={disabled} onChange={(r) => onRows(s.key, r)} />
        </div>
      ) : (
        <SettingField setting={s} value={values[s.key] ?? ''} disabled={disabled} onChange={(v) => onValue(s.key, v)} />
      )}
      {s.hint && <div className="set-fine setting-hint">{s.hint}</div>}
    </div>
  )
}

const listsOf = (settings: ConnectorSetting[]) =>
  Object.fromEntries(settings.filter((s) => s.type === 'list').map((s) => [s.key, parseFolders(s.value ?? '')]))

/** Первая ошибка изменённых значений с подписью поля; '' — всё годится. */
function firstError(settings: ConnectorSetting[], env: Record<string, string>): string {
  for (const s of settings.filter((x) => x.key in env)) {
    const error = valueError(s, env[s.key] ?? '')
    if (error) return `${s.title}: ${error}`
  }
  return ''
}

export default function ConnectorForm({ settings, disabled, onSave }: Props) {
  const [values, setValues] = useState(() => Object.fromEntries(settings.map((s) => [s.key, initialValue(s)])))
  const [lists, setLists] = useState<Record<string, FolderRow[]>>(() => listsOf(settings))
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const folders = Object.fromEntries(Object.entries(lists).map(([k, rows]) => [k, formatFolders(rows)]))
  const current = { ...values, ...folders }
  const env = changedEnv(settings, current)
  const locked = disabled || saving
  const save = async () => {
    const problem = firstError(settings, env)
    setError(problem)
    if (problem) return
    setSaving(true)
    setError(await onSave(env))
    setSaving(false)
  }
  return (
    <div className="connector-form">
      <div className="cap set-label">Настройки</div>
      {settings.map((s) => (
        <SettingRow
          key={s.key}
          setting={s}
          values={values}
          lists={lists}
          disabled={locked}
          onValue={(key, value) => setValues({ ...values, [key]: value })}
          onRows={(key, rows) => setLists({ ...lists, [key]: rows })}
        />
      ))}
      {error && <div className="set-note bad" role="alert">{error}</div>}
      <div className="field-block">
        <button
          type="button"
          className="btn small"
          disabled={locked || Object.keys(env).length === 0}
          onClick={() => void save()}
        >
          {saving ? 'Сохраняется…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}
