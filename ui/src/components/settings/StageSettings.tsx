// Настройки обработчика фразы: включить или выключить, описание.
import type { StageItem } from '../../schema/blocks'

type Props = { stage: StageItem; applying: boolean; onToggle: (on: boolean) => void }

export default function StageSettings({ stage, applying, onToggle }: Props) {
  return (
    <div className="set">
      <h3 className="set-title cut">{stage.title}</h3>
      <div className="set-sub">Обработчик фразы</div>
      <label className="field">
        <span className="lbl">Включён</span>
        <input
          type="checkbox"
          role="switch"
          className="switch"
          checked={stage.enabled}
          disabled={applying}
          onChange={(e) => onToggle(e.target.checked)}
        />
      </label>
      {applying && <div className="set-note">Применяется…</div>}
      {stage.description && (
        <p className="set-text">
          {stage.title}: {stage.description}
        </p>
      )}
    </div>
  )
}
