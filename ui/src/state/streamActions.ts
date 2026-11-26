// Действия с музыкой на колонке: пауза, продолжить, дальше, назад, стоп; громкость музыки.
import type { Client } from './actions'
import type { StreamAction } from './model'
import type { Dispatch } from './request'
import { sendNotify } from './request'

export type StreamActions = {
  /** Управление потоком колонки; отказ ядра — уведомление. */
  controlStream(deviceId: string, action: StreamAction): Promise<void>
  /** Громкость музыки колонки, % (общая громкость колонки — отдельно, в настройках). */
  setStreamVolume(deviceId: string, percent: number): Promise<void>
}

export function createStreamActions(client: Client, dispatch: Dispatch): StreamActions {
  return {
    async controlStream(deviceId, action) {
      const body = { device_id: deviceId, action }
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/streams/control', { body }))
      if (outcome.ok) dispatch({ type: 'stream', stream: outcome.data })
    },
    async setStreamVolume(deviceId, percent) {
      const body = { device_id: deviceId, volume: percent / 100, delta: 0 }
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/streams/volume', { body }))
      if (outcome.ok) dispatch({ type: 'stream', stream: outcome.data })
    },
  }
}
