// Настройки обработчика фразы: включить или выключить, его флажки, описание.
import type { StageItem, StageOption } from '../../schema/blocks'

/** Флажок обработчика в панели: значение и что делать при переключении. */
export type StageOptionRow = StageOption & { checked: boolean; onChange: (on: boolean) => void }

type Props = {
  stage: StageItem
  applying: boolean
  /** Переключать нельзя (применяется или настройки не загружены). */
  locked: boolean
  onToggle: (on: boolean) => void
  /** Флажки обработчика; у выключенного обработчика заблокированы. */
  options?: StageOptionRow[]
}

function Switch({ label, checked, disabled, onChange }: { label: string; checked: boolean; disabled: boolean; onChange: (on: boolean) => void }) {
  return (
    <label className="field">
      <span className="lbl">{label}</span>
      <input type="checkbox" role="switch" className="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
    </label>
  )
}

export default function StageSettings({ stage, applying, locked, onToggle, options = [] }: Props) {
  return (
    <div className="set">
      <h3 className="set-title cut">{stage.title}</h3>
      <div className="set-sub">Обработчик фразы</div>
      <Switch label="Включён" checked={stage.enabled} disabled={locked} onChange={onToggle} />
      {options.map((o) => (
        <div key={o.key}>
          <Switch label={o.label} checked={o.checked} disabled={locked || !stage.enabled} onChange={o.onChange} />
          <div className="set-note">{o.hint}</div>
        </div>
      ))}
      {applying && <div className="set-note">Применяется…</div>}
      {stage.description && (
        <p className="set-text">
          {stage.title}: {stage.description}
        </p>
      )}
    </div>
  )
}
