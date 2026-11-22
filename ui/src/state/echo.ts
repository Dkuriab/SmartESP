// Калибровка эха колонки: событие device_echo → status.devices[].echo; запрос калибровки.
import type { CoreEvent } from '../api/events'
import type { components } from '../api/schema'
import type { Client } from './actions'
import type { CoreState } from './model'
import type { Dispatch } from './request'
import { sendNotify } from './request'

export type Echo = components['schemas']['EchoOut']

const STATES = new Set<Echo['state']>(['current', 'sent', 'running', 'done', 'failed'])

/** Сдвиг из данных события; неполное — null. */
function parseEcho(data: Record<string, unknown>): Echo | null {
  const { state, delay_ms: delay, previous_ms: previous, confidence, error, at } = data
  if (typeof state !== 'string' || !STATES.has(state as Echo['state'])) return null
  if (typeof delay !== 'number' || typeof previous !== 'number' || typeof confidence !== 'number') return null
  if (typeof at !== 'number') return null
  const text = typeof error === 'string' ? error : ''
  return { state: state as Echo['state'], delay_ms: delay, previous_ms: previous, confidence, error: text, at }
}

/** device_echo: сдвиг образца колонки — сразу в status (без ожидания опроса). */
export function applyEchoEvent(state: CoreState, e: CoreEvent): CoreState {
  const id = e.data.device_id
  const echo = parseEcho(e.data)
  if (!state.status || typeof id !== 'string' || !echo) return state
  const devices = state.status.devices.map((d) => (d.device_id === id ? { ...d, echo } : d))
  return { ...state, status: { ...state.status, devices } }
}

export type EchoActions = {
  /** Калибровка эха на колонке; отказ ядра — уведомление, ход и итог — событиями device_echo. */
  calibrateEcho(deviceId: string): Promise<void>
}

export function createEchoActions(client: Client, dispatch: Dispatch): EchoActions {
  return {
    async calibrateEcho(deviceId) {
      const params = { path: { device_id: deviceId } }
      await sendNotify(dispatch, () => client.POST('/api/v1/devices/{device_id}/echo/calibrate', { params }))
    },
  }
}
