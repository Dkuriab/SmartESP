// Действия со своими звуками колонок: обзор, замена файлом, встроенный, прослушивание, повтор доставки.
import type { components } from '../api/schema'
import type { Client } from './actions'
import type { Dispatch } from './request'
import { send, sendNotify } from './request'

export type SoundsOverview = components['schemas']['SoundsOut']
export type DeviceSoundsInfo = components['schemas']['DeviceSoundsOut']
export type DeviceSound = components['schemas']['DeviceSoundOut']
export type SoundTone = DeviceSound['tone']

/** Файл звука больше этого ядро не примет (413); проверяем до загрузки. */
export const MAX_SOUND_BYTES = 10 * 1024 * 1024
export const SOUND_TOO_BIG = 'Файл больше 10 МБ — для сигнала нужен короткий звук'

export type SoundActions = {
  /** Назначения и доставка по колонкам; ошибка — null (без уведомления: обзор перечитывается часто). */
  loadSounds(): Promise<SoundsOverview | null>
  /** Заменяет звук сигнала файлом: всем колонкам (deviceId null) или одной; отказ — уведомление. */
  uploadSound(tone: SoundTone, file: File, deviceId: string | null): Promise<boolean>
  /** Встроенный звук сигнала всем колонкам (null) или одной. */
  resetSound(tone: SoundTone, deviceId: string | null): Promise<boolean>
  /** Свой звук (WAV) по SHA-256 или null. */
  fetchSound(sha256: string): Promise<Blob | null>
  /** Повторить доставку на колонки после неудачи. */
  resyncSounds(): Promise<void>
}

export function createSoundActions(client: Client, dispatch: Dispatch): SoundActions {
  return {
    async loadSounds() {
      const outcome = await send(dispatch, () => client.GET('/api/v1/sounds'))
      return outcome.ok ? outcome.data : null
    },
    async uploadSound(tone, file, deviceId) {
      if (file.size > MAX_SOUND_BYTES) {
        dispatch({ type: 'notice', notice: { text: SOUND_TOO_BIG, tone: 'error' } })
        return false
      }
      const params = { path: { tone }, query: deviceId ? { device_id: deviceId } : {} }
      const data = new FormData()
      data.append('file', file)
      // в схеме файл — строка (binary); на деле уходит FormData с самим файлом
      const body = { file: file as unknown as string }
      const outcome = await sendNotify(dispatch, () =>
        client.POST('/api/v1/sounds/{tone}', { params, body, bodySerializer: () => data }),
      )
      if (outcome.ok && outcome.data.trimmed) {
        dispatch({ type: 'notice', notice: { text: 'Звук длиннее 3 с — обрезан', tone: 'ok' } })
      }
      return outcome.ok
    },
    async resetSound(tone, deviceId) {
      const params = { path: { tone }, query: deviceId ? { device_id: deviceId } : {} }
      const outcome = await sendNotify(dispatch, () => client.DELETE('/api/v1/sounds/{tone}', { params }))
      return outcome.ok
    },
    async fetchSound(sha256) {
      const params = { path: { sha256 } }
      const outcome = await sendNotify(dispatch, () => client.GET('/api/v1/sounds/files/{sha256}', { params, parseAs: 'blob' }))
      return outcome.ok ? (outcome.data as Blob) : null
    },
    async resyncSounds() {
      await sendNotify(dispatch, () => client.POST('/api/v1/sounds/sync'))
    },
  }
}
