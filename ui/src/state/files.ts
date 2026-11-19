// Файл на колонке: фаза по действиям и событиям ядра, итог — уведомлением.
import type { CoreEvent } from '../api/events'
import type { CoreState, FilePhase, Notice } from './model'

/** Новая фаза файла колонки; onlyFrom — менять, только если сейчас эта фаза. */
export function setFilePhase(
  state: CoreState,
  deviceId: string,
  phase: FilePhase | null,
  onlyFrom?: FilePhase,
): CoreState {
  if (onlyFrom !== undefined && state.files[deviceId] !== onlyFrom) return state
  const files = { ...state.files }
  if (phase === null) delete files[deviceId]
  else files[deviceId] = phase
  return { ...state, files }
}

function deviceName(state: CoreState, id: string): string {
  return state.status?.devices.find((d) => d.device_id === id)?.name || id
}

/** Уведомление об итоге файла по delivery ядра. */
export function finishedNotice(delivery: unknown, name: string): Notice {
  switch (delivery) {
    case 'delivered':
      return { text: `Файл доигран на колонке «${name}»`, tone: 'ok' }
    case 'interrupted':
      return { text: `Файл на колонке «${name}» остановлен`, tone: 'ok' }
    case 'busy':
      return { text: `Колонка «${name}» была занята — файл не проигран`, tone: 'error' }
    default:
      return { text: `Колонка «${name}» не доиграла файл: нет связи`, tone: 'error' }
  }
}

/** playback_started — играет; playback_finished — не играет и уведомление об итоге. */
export function applyFileEvent(state: CoreState, e: CoreEvent): CoreState {
  const id = e.data.device_id
  if (typeof id !== 'string' || !id) return state
  if (e.kind === 'playback_started') return setFilePhase(state, id, 'playing')
  const notice = finishedNotice(e.data.delivery, deviceName(state, id))
  return { ...setFilePhase(state, id, null), notice }
}
