// Настройки диспетчера: модель из Ollama и промпт с кнопкой «Сохранить».
import { useState } from 'react'
import { dispatcherInfo, isApplying } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Model } from '../../state/model'

type Props = { state: CoreState; actions: CoreActions }

const APPLYING = 'Применяется…'

/** «4,1 ГБ» из байтов. */
function gigabytes(bytes: number): string {
  const gb = bytes / 1e9
  return `${gb.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ГБ`
}

type ModelProps = { current: string; models: Model[]; disabled: boolean; onPick: (model: string) => void }

function ModelField({ current, models, disabled, onPick }: ModelProps) {
  // текущая модель видна, даже если её нет в списке (Ollama недоступна)
  const known = models.some((m) => m.name === current)
  return (
    <label className="field">
      <span className="lbl">Модель</span>
      <select className="val" value={current} disabled={disabled} onChange={(e) => onPick(e.target.value)}>
        {!known && <option value={current}>{current || '—'}</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name}>
            {`${m.name} · ${gigabytes(m.size_bytes)}`}
          </option>
        ))}
      </select>
    </label>
  )
}

type PromptProps = { current: string; applying: boolean; onSave: (text: string) => void }

function PromptField({ current, applying, onSave }: PromptProps) {
  const [draft, setDraft] = useState(current)
  const changed = draft !== current
  return (
    <div className="field field-block">
      <label className="field-block">
        <span className="cap">Промпт</span>
        <textarea className="prompt" rows={8} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <button type="button" className="btn" disabled={!changed || applying} onClick={() => onSave(draft)}>
        {applying ? APPLYING : 'Сохранить'}
      </button>
    </div>
  )
}

export default function DispatcherSettings({ state, actions }: Props) {
  const info = dispatcherInfo(state)
  const reachable = state.status?.ollama.reachable ?? true
  const applying = isApplying(state)
  return (
    <div className="set">
      <h3 className="set-title">⚡️ Диспетчер</h3>
      <div className="set-sub">Исполнитель · отвечает первым</div>
      {!info && <p className="set-hint">Диспетчер не настроен</p>}
      {info && (
        <>
          <ModelField
            current={info.model}
            models={state.models ?? []}
            // пока изменение применяется, executors в настройках старые: новая правка затёрла бы его
            disabled={!reachable || applying}
            onPick={(model) => void actions.setDispatcher({ model })}
          />
          {!reachable && <div className="set-note warn">Ollama недоступна</div>}
          {applying && <div className="set-note">{APPLYING}</div>}
          {/* key: после применения черновик берёт новый промпт */}
          <PromptField key={info.systemPrompt} current={info.systemPrompt} applying={applying} onSave={(text) => void actions.setDispatcher({ system_prompt: text })} />
        </>
      )}
    </div>
  )
}
