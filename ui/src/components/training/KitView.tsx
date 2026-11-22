// Набор для обучения: цели (что слышать и что нет), запись с колонки, сколько записей у кого.
import { useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import type { TrainKit, TrainTarget } from '../../state/trainingActions'
import PhraseTable from './PhraseTable'
import RecordPanel from './RecordPanel'
import TargetEditor from './TargetEditor'
import TrainPanel from './TrainPanel'

type Props = {
  kit: TrainKit
  state: CoreState
  actions: CoreActions
  onChanged: (kit: TrainKit) => void
  onRecorded: () => void
}

export default function KitView({ kit, state, actions, onChanged, onRecorded }: Props) {
  const [phrase, setPhrase] = useState(kit.phrases[0]?.phrase ?? '')
  const [saving, setSaving] = useState(false)
  const save = async (targets: TrainTarget[]) => {
    setSaving(true)
    const changed = await actions.saveTargets(kit.id, targets)
    setSaving(false)
    if (changed) onChanged(changed)
  }
  const update = (i: number, target: TrainTarget) => void save(kit.targets.map((t, j) => (j === i ? target : t)))
  const current = kit.phrases.some((p) => p.phrase === phrase) ? phrase : (kit.phrases[0]?.phrase ?? '')
  return (
    <div className="training-main">
      <section className="training-col" aria-label="Цели">
        <div className="cap">Цели — каждая отдельная модель</div>
        {kit.targets.map((t, i) => (
          <TargetEditor key={t.id} target={t} disabled={saving} onChange={(target) => update(i, target)} />
        ))}
      </section>
      <section className="training-col" aria-label="Запись">
        <RecordPanel kit={kit} phrase={current} onPhrase={setPhrase} state={state} actions={actions} onRecorded={onRecorded} />
        <PhraseTable kit={kit} selected={current} onSelect={setPhrase} />
      </section>
      {kit.steps.length > 0 && (
        <section className="training-col" aria-label="Обучение">
          <TrainPanel kit={kit} actions={actions} />
        </section>
      )}
    </div>
  )
}
