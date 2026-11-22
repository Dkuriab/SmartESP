// Данные вкладки «Люди»: люди, модель узнавания (пока качается — опрос) и последние узнавания.
import { useCallback, useEffect, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import type { Person, Recognition, SpeakerModel } from '../../state/peopleActions'

const POLL_MS = 1000 // как часто спрашивать ход скачивания модели

export type PeopleData = {
  people: Person[] | null
  model: SpeakerModel | null
  recognitions: Recognition[]
  /** Перечитать людей (после записи или удаления образца). */
  reload: () => void
  /** Заменить человека в списке (после правки) или убрать (null). */
  replace: (id: string, person: Person | null) => void
  download: () => void
}

/** Модель узнавания: загрузка, скачивание по кнопке и опрос, пока качается. */
function useSpeakerModel(actions: CoreActions, online: boolean) {
  const [model, setModel] = useState<SpeakerModel | null>(null)
  const { loadSpeakerModel, downloadSpeakerModel } = actions
  useEffect(() => {
    if (online) void loadSpeakerModel().then(setModel)
  }, [online, loadSpeakerModel])
  useEffect(() => {
    if (!model?.downloading) return
    const timer = setInterval(() => void loadSpeakerModel().then(setModel), POLL_MS)
    return () => clearInterval(timer)
  }, [model?.downloading, loadSpeakerModel])
  const download = () => void downloadSpeakerModel().then((m) => m && setModel(m))
  return { model, download }
}

export function usePeople(state: CoreState, actions: CoreActions): PeopleData {
  const online = state.connection === 'online'
  const [people, setPeople] = useState<Person[] | null>(null)
  const [recognitions, setRecognitions] = useState<Recognition[]>([])
  const { loadPeople, loadRecognitions } = actions
  const reload = useCallback(() => void loadPeople().then(setPeople), [loadPeople])
  useEffect(() => {
    if (online) reload()
  }, [online, reload])
  // новый ход в ленте — возможно, новое узнавание
  useEffect(() => {
    if (online) void loadRecognitions().then(setRecognitions)
  }, [online, loadRecognitions, state.turns])
  const replace = (id: string, person: Person | null) =>
    setPeople((list) => (list ?? []).flatMap((p) => (p.id !== id ? [p] : person ? [person] : [])))
  return { people, recognitions, reload, replace, ...useSpeakerModel(actions, online) }
}
