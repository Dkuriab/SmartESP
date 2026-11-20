// Поля настроек исполнителя: строка с сохранением по Enter/потере фокуса, модель,
// рассуждение, промпт с «Сохранить», итоговый промпт.
import { useState } from 'react'
import type { Reasoning } from '../../schema/blocks'
import { REASONING_LEVELS } from '../../schema/blocks'
import type { Model } from '../../state/model'

export const APPLYING = 'Применяется…'

/** «4,1 ГБ» из байтов. */
function gigabytes(bytes: number): string {
  const gb = bytes / 1e9
  return `${gb.toLocaleString('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} ГБ`
}

type CommitProps = {
  label: string
  value: string
  placeholder?: string
  disabled: boolean
  /** Пустое значение не сохраняется (черновик возвращается к прежнему). */
  required?: boolean
  onCommit: (text: string) => void
}

/** Строка, сохраняется по Enter или потере фокуса, если изменилась. Родитель задаёт key по value. */
export function CommitField({ label, value, placeholder, disabled, required = false, onCommit }: CommitProps) {
  const [draft, setDraft] = useState(value)
  const save = () => {
    const text = draft.trim()
    if (text === value.trim() || (required && !text)) setDraft(value)
    else onCommit(text)
  }
  return (
    <label className="field">
      <span className="lbl">{label}</span>
      <input
        className="val"
        value={draft}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        onBlur={save}
      />
    </label>
  )
}

/** Подпись модели в списке: размер и пометка, если она не умеет инструменты. */
function modelLabel(m: Model): string {
  const label = `${m.name} · ${gigabytes(m.size_bytes)}`
  return m.supports_tools ? label : `${label} (без инструментов)`
}

type ModelProps = { current: string; models: Model[]; disabled: boolean; onPick: (model: string) => void }

export function ModelField({ current, models, disabled, onPick }: ModelProps) {
  // текущая модель видна, даже если её нет в списке (Ollama недоступна)
  const known = models.some((m) => m.name === current)
  return (
    <label className="field">
      <span className="lbl">Модель</span>
      <select className="val" value={current} disabled={disabled} onChange={(e) => onPick(e.target.value)}>
        {!known && <option value={current}>{current || '—'}</option>}
        {models.map((m) => (
          <option key={m.name} value={m.name}>
            {modelLabel(m)}
          </option>
        ))}
      </select>
    </label>
  )
}

const REASONING_TITLES: Record<Reasoning, string> = { off: 'Нет', low: 'Низкое', medium: 'Среднее', high: 'Высокое' }

type ReasoningProps = { current: Reasoning; model: string; disabled: boolean; onPick: (reasoning: Reasoning) => void }

/** Подсказка к уровню: у gpt-oss рассуждение не выключается; другие модели могут его не уметь. */
export function reasoningHint(model: string, reasoning: Reasoning): string | null {
  // список моделей не говорит, умеет ли модель рассуждать: подсказка общая, решает ядро
  const gptOss = model.toLowerCase().includes('gpt-oss')
  if (gptOss && reasoning === 'off') return 'у gpt-oss рассуждение не выключается: «Нет» — это «Низкое»'
  if (!gptOss && reasoning !== 'off') return 'эта модель может не поддерживать рассуждение — тогда ядро ответит без него'
  return null
}

/** Сколько модель думает перед ответом: дольше думает — позже начинает говорить. */
export function ReasoningField({ current, model, disabled, onPick }: ReasoningProps) {
  const hint = reasoningHint(model, current)
  return (
    <>
      <label className="field">
        <span className="lbl">Рассуждение</span>
        <select className="val" value={current} disabled={disabled} onChange={(e) => onPick(e.target.value as Reasoning)}>
          {REASONING_LEVELS.map((level) => (
            <option key={level} value={level}>
              {REASONING_TITLES[level]}
            </option>
          ))}
        </select>
      </label>
      {hint && <div className="set-note">{hint}</div>}
    </>
  )
}

type PromptProps = { current: string; applying: boolean; onSave: (text: string) => void }

/** Промпт: «Сохранить» активна, только если текст изменён. Родитель задаёт key по current. */
export function PromptField({ current, applying, onSave }: PromptProps) {
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

/** Промпт, с которым работает исполнитель: свой + правила (обработчиков, передачи); свёрнут. */
export function FinalPrompt({ text }: { text: string }) {
  return (
    <details className="final-prompt">
      <summary className="cap">Итоговый промпт</summary>
      <pre className="prompt prompt-final">{text}</pre>
    </details>
  )
}
