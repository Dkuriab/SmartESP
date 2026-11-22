// Действия вкладки «Люди»: люди дома, образцы голоса с колонки, последние узнавания, модель узнавания.
import type { components } from '../api/schema'
import type { Client } from './actions'
import type { Dispatch } from './request'
import { send, sendNotify } from './request'

export type Person = components['schemas']['PersonOut']
export type VoiceSample = components['schemas']['SampleOut']
export type Recognition = components['schemas']['RecognitionOut']
export type SpeakerModel = components['schemas']['SpeakerModelOut']

/** Итог записи образца: образец или текст отказа («колонка занята», «ничего не услышала»). */
export type SampleOutcome = { ok: true; sample: VoiceSample } | { ok: false; text: string }

export type PeopleActions = {
  /** Люди с образцами; ошибка — уведомление и пустой список. */
  loadPeople(): Promise<Person[]>
  /** Добавляет человека; человек или null (ошибка — уведомлением). */
  addPerson(name: string): Promise<Person | null>
  /** Переименовывает; человек после правки или null (ошибка — уведомлением). */
  renamePerson(id: string, name: string): Promise<Person | null>
  /** Удаляет человека с образцами; true — удалён. */
  deletePerson(id: string): Promise<boolean>
  /** Пишет образец голоса с колонки (колонка пикает и слушает до паузы). */
  recordSample(personId: string, deviceId: string): Promise<SampleOutcome>
  /** Удаляет образец; true — удалён. */
  deleteSample(personId: string, sampleId: string): Promise<boolean>
  /** Последние узнавания, новые первыми; ошибка — пусто. */
  loadRecognitions(): Promise<Recognition[]>
  /** Модель узнавания голоса; ошибка — null. */
  loadSpeakerModel(): Promise<SpeakerModel | null>
  /** Начинает скачивание модели; состояние или null (ошибка — уведомлением). */
  downloadSpeakerModel(): Promise<SpeakerModel | null>
}

export function createPeopleActions(client: Client, dispatch: Dispatch): PeopleActions {
  const path = (id: string) => ({ params: { path: { person_id: id } } })
  return {
    async loadPeople() {
      const outcome = await sendNotify(dispatch, () => client.GET('/api/v1/people'))
      return outcome.ok ? outcome.data : []
    },
    async addPerson(name) {
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/people', { body: { name } }))
      return outcome.ok ? outcome.data : null
    },
    async renamePerson(id, name) {
      const outcome = await sendNotify(dispatch, () => client.PATCH('/api/v1/people/{person_id}', { ...path(id), body: { name } }))
      return outcome.ok ? outcome.data : null
    },
    async deletePerson(id) {
      return (await sendNotify(dispatch, () => client.DELETE('/api/v1/people/{person_id}', path(id)))).ok
    },
    async recordSample(personId, deviceId) {
      const body = { device_id: deviceId }
      const outcome = await send(dispatch, () => client.POST('/api/v1/people/{person_id}/samples', { ...path(personId), body }))
      return outcome.ok ? { ok: true, sample: outcome.data } : { ok: false, text: outcome.text || 'Не удалось записать' }
    },
    async deleteSample(personId, sampleId) {
      const params = { path: { person_id: personId, sample_id: sampleId } }
      return (await sendNotify(dispatch, () => client.DELETE('/api/v1/people/{person_id}/samples/{sample_id}', { params }))).ok
    },
    async loadRecognitions() {
      const outcome = await send(dispatch, () => client.GET('/api/v1/people/recognitions'))
      return outcome.ok ? outcome.data : []
    },
    async loadSpeakerModel() {
      const outcome = await send(dispatch, () => client.GET('/api/v1/people/model'))
      return outcome.ok ? outcome.data : null
    },
    async downloadSpeakerModel() {
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/people/model'))
      return outcome.ok ? outcome.data : null
    },
  }
}
