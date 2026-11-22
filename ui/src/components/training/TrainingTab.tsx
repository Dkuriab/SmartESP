// Вкладка «Обучение»: наборы для обучения слева, справа — цели, запись с колонки и счёт записей.
import { useCallback, useEffect, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import type { TrainKit } from '../../state/trainingActions'
import KitView from './KitView'
import './training.css'

type Props = { state: CoreState; actions: CoreActions }

export default function TrainingTab({ state, actions }: Props) {
  const [kits, setKits] = useState<TrainKit[] | null>(null)
  const [kitId, setKitId] = useState('')
  const online = state.connection === 'online'
  const { loadTraining } = actions
  const reload = useCallback(() => void loadTraining().then(setKits), [loadTraining])
  useEffect(() => {
    if (online) reload()
  }, [online, reload])
  const kit = kits?.find((k) => k.id === kitId) ?? kits?.[0]
  const replace = (changed: TrainKit) => setKits((list) => (list ?? []).map((k) => (k.id === changed.id ? changed : k)))
  return (
    <div className="panel training-full">
      <nav className="training-side" aria-label="Наборы для обучения">
        <div className="cap">Что обучаем</div>
        {(kits ?? []).map((k) => (
          <button key={k.id} type="button" className={`training-kit${k.id === kit?.id ? ' on' : ''}`} onClick={() => setKitId(k.id)}>
            {k.title}
          </button>
        ))}
        {kit && <p className="set-note">{kit.description}</p>}
      </nav>
      {kit ? (
        <KitView key={kit.id} kit={kit} state={state} actions={actions} onChanged={replace} onRecorded={reload} />
      ) : (
        <div className="set-note">{kits === null ? 'Загрузка…' : 'Наборов для обучения нет (папка trainers/)'}</div>
      )}
    </div>
  )
}
