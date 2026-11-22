// Действия с файлом на колонке: загрузка (multipart) и остановка.
import type { Client } from './actions'
import type { Dispatch } from './request'
import { sendNotify } from './request'

export type FileActions = {
  /** Проиграть файл на колонке; ошибка — уведомление, итог проигрывания придёт событием. */
  playFile(deviceId: string, file: File): Promise<void>
  /** Остановить файл на колонке; файл не играл — уведомление. */
  stopFile(deviceId: string): Promise<void>
  /** Прошивка (.bin) на колонку по воздуху; ход — в status (device.update); отказ — уведомление. */
  installFirmware(deviceId: string, file: File): Promise<boolean>
}

export const NOT_PLAYING = 'На колонке не играет файл'
/** Больше ядро не примет (413); проверяем до загрузки — иначе браузер часто видит обрыв связи. */
export const MAX_FILE_BYTES = 50 * 1024 * 1024
export const TOO_BIG = 'Файл больше 50 МБ — ядро такой не примет'
const PLAY_PATH = '/api/v1/devices/{device_id}/play'

/** Тело запроса: файл в поле audio. */
function form(file: File): FormData {
  const data = new FormData()
  data.append('audio', file)
  return data
}

export function createFileActions(client: Client, dispatch: Dispatch): FileActions {
  return {
    async playFile(deviceId, file) {
      if (file.size > MAX_FILE_BYTES) {
        dispatch({ type: 'notice', notice: { text: TOO_BIG, tone: 'error' } })
        return
      }
      dispatch({ type: 'filePhase', deviceId, phase: 'sending' })
      const params = { path: { device_id: deviceId } }
      // в схеме файл — строка (binary); на деле уходит FormData с самим файлом
      const body = { audio: file as unknown as string }
      const outcome = await sendNotify(dispatch, () =>
        client.POST(PLAY_PATH, { params, body, bodySerializer: () => form(file) }),
      )
      // событие playback_started могло прийти раньше ответа, playback_finished — тоже
      if (outcome.ok) dispatch({ type: 'filePhase', deviceId, phase: 'playing', onlyFrom: 'sending' })
      else dispatch({ type: 'filePhase', deviceId, phase: null })
    },
    async installFirmware(deviceId, file) {
      const params = { path: { device_id: deviceId } }
      const body = { firmware: file as unknown as string }
      const data = new FormData()
      data.append('firmware', file)
      const outcome = await sendNotify(dispatch, () =>
        client.POST('/api/v1/devices/{device_id}/firmware', { params, body, bodySerializer: () => data }),
      )
      if (outcome.ok) dispatch({ type: 'notice', notice: { text: 'Прошивка отправлена: колонка скачает её и перезагрузится', tone: 'ok' } })
      return outcome.ok
    },
    async stopFile(deviceId) {
      const params = { path: { device_id: deviceId } }
      const outcome = await sendNotify(dispatch, () => client.DELETE(PLAY_PATH, { params }))
      if (!outcome.ok) return
      if (!outcome.data.stopped) dispatch({ type: 'notice', notice: { text: NOT_PLAYING, tone: 'ok' } })
      dispatch({ type: 'filePhase', deviceId, phase: null })
    },
  }
}
