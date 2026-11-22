// Действия со своими звуками колонок: обзор, замена файлом, встроенный, копия на другие колонки,
// прослушивание, повтор доставки. Звуки задаются только колонке (не в сети — получит при подключении).
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
  /** Заменяет звук сигнала колонки файлом; отказ — уведомление. */
  uploadSound(tone: SoundTone, file: File, deviceId: string): Promise<boolean>
  /** Встроенный звук сигнала колонки. */
  resetSound(tone: SoundTone, deviceId: string): Promise<boolean>
  /** Набор звуков колонки — всем другим известным колонкам; итог — уведомлением. */
  copySounds(deviceId: string): Promise<boolean>
  /** Свой звук (WAV) по SHA-256 или null. */
  fetchSound(sha256: string): Promise<Blob | null>
  /** Повторить доставку на колонку после неудачи. */
  resyncSounds(deviceId: string): Promise<void>
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
      const params = { path: { tone }, query: { device_id: deviceId } }
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
      const params = { path: { tone }, query: { device_id: deviceId } }
      const outcome = await sendNotify(dispatch, () => client.DELETE('/api/v1/sounds/{tone}', { params }))
      return outcome.ok
    },
    async fetchSound(sha256) {
      const params = { path: { sha256 } }
      const outcome = await sendNotify(dispatch, () => client.GET('/api/v1/sounds/files/{sha256}', { params, parseAs: 'blob' }))
      return outcome.ok ? (outcome.data as Blob) : null
    },
    async copySounds(deviceId) {
      const params = { query: { device_id: deviceId } }
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/sounds/copy', { params }))
      if (!outcome.ok) return false
      const count = outcome.data.devices.length
      const text = count ? `Звуки скопированы на другие колонки: ${count}` : 'Других колонок нет'
      dispatch({ type: 'notice', notice: { text, tone: 'ok' } })
      return true
    },
    async resyncSounds(deviceId) {
      await sendNotify(dispatch, () => client.POST('/api/v1/sounds/sync', { params: { query: { device_id: deviceId } } }))
    },
  }
}
