// Цель обучения: «Откликаться на» и «Не откликаться на» — фразы ярлыками, добавить по Enter.
import { useState } from 'react'
import type { TrainTarget } from '../../state/trainingActions'

type ListProps = { label: string; phrases: string[]; disabled: boolean; onChange: (phrases: string[]) => void }

/** Список фраз: ярлык с «×», поле «Добавить» (Enter). Последнюю фразу «Откликаться на» убрать нельзя. */
export function PhraseList({ label, phrases, disabled, onChange }: ListProps) {
  const [draft, setDraft] = useState('')
  const add = () => {
    const phrase = draft.trim().replace(/\s+/g, ' ')
    setDraft('')
    if (phrase && !phrases.includes(phrase)) onChange([...phrases, phrase])
  }
  return (
    <div className="phrase-list" role="group" aria-label={label}>
      <span className="lbl">{label}</span>
      <div className="chips">
        {phrases.map((p) => (
          <span key={p} className="chip">
            {p}
            <button type="button" aria-label={`Убрать «${p}»`} disabled={disabled} onClick={() => onChange(phrases.filter((x) => x !== p))}>
              ×
            </button>
          </span>
        ))}
        <input className="chip-input" value={draft} placeholder="Добавить…" maxLength={40} disabled={disabled}
          aria-label={`${label}: добавить фразу`} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
      </div>
    </div>
  )
}

type Props = { target: TrainTarget; disabled: boolean; onChange: (target: TrainTarget) => void }

export default function TargetEditor({ target, disabled, onChange }: Props) {
  const negative = target.negative ?? []
  return (
    <div className="target-card">
      <div className="target-title">{target.title}</div>
      <PhraseList label="Откликаться на" phrases={target.positive} disabled={disabled}
        onChange={(positive) => positive.length > 0 && onChange({ ...target, positive })} />
      <PhraseList label="Не откликаться на" phrases={negative} disabled={disabled} onChange={(next) => onChange({ ...target, negative: next })} />
    </div>
  )
}
