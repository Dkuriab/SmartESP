// Вкладка «Люди»: кто живёт дома и как звучит их голос. Слева — люди, справа — выбранный
// человек (образцы голоса с колонки), внизу — последние узнавания.
import { useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import ModelBanner from './ModelBanner'
import PersonList from './PersonList'
import PersonView from './PersonView'
import Recognitions from './Recognitions'
import { usePeople } from './usePeople'
import '../training/training.css' // общие карточки записи и таблица
import './people.css'

type Props = { state: CoreState; actions: CoreActions }

export default function PeopleTab({ state, actions }: Props) {
  const data = usePeople(state, actions)
  const [selectedId, setSelectedId] = useState('')
  const person = data.people?.find((p) => p.id === selectedId) ?? data.people?.[0]
  const add = async (name: string) => {
    const added = await actions.addPerson(name)
    if (added) {
      data.reload()
      setSelectedId(added.id)
    }
    return Boolean(added)
  }
  return (
    <div className="panel people-full">
      <PersonList people={data.people} selectedId={person?.id ?? ''} onSelect={setSelectedId} onAdd={add} />
      <div className="people-main">
        {data.model && <ModelBanner model={data.model} onDownload={data.download} />}
        {person ? (
          <PersonView key={person.id} person={person} modelReady={Boolean(data.model?.ready)} state={state} actions={actions} data={data} />
        ) : (
          <div className="set-note">{data.people === null ? 'Загрузка…' : 'Добавь первого человека — слева, по имени'}</div>
        )}
        <Recognitions items={data.recognitions} devices={state.status?.devices ?? []} />
      </div>
    </div>
  )
}
