// Выбранный человек: имя (переименовать), удаление, запись образцов голоса и их список.
import { useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import type { Person } from '../../state/peopleActions'
import SampleList from './SampleList'
import SampleRecorder from './SampleRecorder'
import type { PeopleData } from './usePeople'

type Props = { person: Person; modelReady: boolean; state: CoreState; actions: CoreActions; data: PeopleData }

/** Имя с кнопкой «Сохранить» (видна, когда имя изменили). */
function NameField({ person, actions, data }: Omit<Props, 'modelReady' | 'state'>) {
  const [name, setName] = useState(person.name)
  const changed = name.trim() !== person.name && name.trim() !== ''
  const save = async () => {
    const renamed = await actions.renamePerson(person.id, name.trim())
    if (renamed) data.replace(person.id, renamed)
  }
  return (
    <label className="field">
      <span className="lbl">Имя</span>
      <input className="val" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} />
      {changed && <button type="button" className="btn" onClick={() => void save()}>Сохранить</button>}
    </label>
  )
}

export default function PersonView({ person, modelReady, state, actions, data }: Props) {
  const [confirm, setConfirm] = useState(false)
  const remove = async () => {
    if (await actions.deletePerson(person.id)) data.replace(person.id, null)
  }
  return (
    <section className="people-card" aria-label={person.name}>
      <NameField person={person} actions={actions} data={data} />
      <SampleRecorder person={person} modelReady={modelReady} state={state} actions={actions} onRecorded={data.reload} />
      <SampleList person={person} devices={state.status?.devices ?? []} actions={actions} onChanged={data.reload} />
      {person.stale_samples > 0 && (
        <div className="set-note warn">{`Образцов от прежней модели: ${person.stale_samples} — в узнавании не участвуют, запиши голос заново.`}</div>
      )}
      <div className="record-buttons">
        {confirm ? (
          <>
            <button type="button" className="btn btn-danger" onClick={() => void remove()}>{`Удалить ${person.name} и образцы`}</button>
            <button type="button" className="btn btn-plain" onClick={() => setConfirm(false)}>Отмена</button>
          </>
        ) : (
          <button type="button" className="btn btn-plain" onClick={() => setConfirm(true)}>Удалить человека</button>
        )}
      </div>
    </section>
  )
}
