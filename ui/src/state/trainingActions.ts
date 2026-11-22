// Действия вкладки «Обучение»: наборы и цели, запись фраз с колонки, прослушивание и удаление записей.
import type { components } from '../api/schema'
import type { Client } from './actions'
import type { Dispatch } from './request'
import { send, sendNotify } from './request'

export type TrainKit = components['schemas']['KitOut']
export type TrainTarget = components['schemas']['TargetIO']
export type PhraseRecording = components['schemas']['RecordingOut']

/** Что записать: колонка, фраза из целей набора, чей голос. */
export type RecordRequest = { kit: string; deviceId: string; phrase: string; person: string }
/** Итог записи: запись или текст отказа («колонка занята», «ничего не услышала»). */
export type RecordOutcome = { ok: true; recording: PhraseRecording } | { ok: false; text: string }

export type TrainingActions = {
  /** Наборы с целями и счётом записей; ошибка — уведомление и пустой список. */
  loadTraining(): Promise<TrainKit[]>
  /** Заменяет цели набора; набор после правки или null (ошибка — уведомлением). */
  saveTargets(kit: string, targets: TrainTarget[]): Promise<TrainKit | null>
  /** Пишет фразу с колонки (колонка пикает и слушает до паузы). */
  recordPhrase(request: RecordRequest): Promise<RecordOutcome>
  /** Записи фразы человека, от старых к новым; ошибка — пусто. */
  listRecordings(kit: string, phrase: string, person: string): Promise<PhraseRecording[]>
  /** Звук записи (WAV) или null. */
  fetchRecording(kit: string, phrase: string, person: string, name: string): Promise<Blob | null>
  /** Удаляет запись; true — удалена. */
  deleteRecording(kit: string, phrase: string, person: string, name: string): Promise<boolean>
}

export function createTrainingActions(client: Client, dispatch: Dispatch): TrainingActions {
  return {
    async loadTraining() {
      const outcome = await sendNotify(dispatch, () => client.GET('/api/v1/training'))
      return outcome.ok ? outcome.data : []
    },
    async saveTargets(kit, targets) {
      const params = { path: { kit } }
      const outcome = await sendNotify(dispatch, () => client.PUT('/api/v1/training/{kit}/targets', { params, body: targets }))
      return outcome.ok ? outcome.data : null
    },
    async recordPhrase({ kit, deviceId, phrase, person }) {
      const body = { device_id: deviceId, phrase, person }
      const outcome = await send(dispatch, () => client.POST('/api/v1/training/{kit}/record', { params: { path: { kit } }, body }))
      return outcome.ok ? { ok: true, recording: outcome.data } : { ok: false, text: outcome.text || 'Не удалось записать' }
    },
    async listRecordings(kit, phrase, person) {
      const params = { path: { kit }, query: { phrase, person } }
      const outcome = await send(dispatch, () => client.GET('/api/v1/training/{kit}/recordings', { params }))
      return outcome.ok ? outcome.data : []
    },
    async fetchRecording(kit, phrase, person, name) {
      const params = { path: { kit, name }, query: { phrase, person } }
      const outcome = await send(dispatch, () => client.GET('/api/v1/training/{kit}/recordings/{name}', { params, parseAs: 'blob' }))
      return outcome.ok ? (outcome.data as Blob) : null
    },
    async deleteRecording(kit, phrase, person, name) {
      const params = { path: { kit, name }, query: { phrase, person } }
      const outcome = await sendNotify(dispatch, () => client.DELETE('/api/v1/training/{kit}/recordings/{name}', { params }))
      return outcome.ok
    },
  }
}
