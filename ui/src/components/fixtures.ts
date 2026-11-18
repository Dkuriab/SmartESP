// Общие данные для тестов компонентов: состояние ядра и поддельные действия.
import { vi } from 'vitest'
import type { CoreActions } from '../state/actions'
import type { CoreState, Status, Turn } from '../state/model'
import { initialState } from '../state/model'

export function makeTurn(id: number, over: Partial<Turn> = {}): Turn {
  return {
    turn_id: id,
    device_id: 'aa:bb',
    device_name: 'Кухня',
    text: `вопрос ${id}`,
    annotations: [],
    style: 'normal',
    answer: `ответ ${id}`,
    status: 'ok',
    ...over,
  }
}

export function makeStatus(over: Partial<Status> = {}): Status {
  return {
    version: '1',
    uptime_s: 5,
    state: 'ready',
    ollama: { reachable: true, loaded: [] },
    devices: [
      { device_id: 'a', name: 'Кухня', connected: true, remote: '', fw: '' },
      { device_id: 'b', name: 'Спальня', connected: false, remote: '', fw: '' },
    ],
    voice: {} as Status['voice'],
    applying: false,
    restart_required: false,
    ...over,
  }
}

export function makeState(over: Partial<CoreState> = {}): CoreState {
  return { ...initialState('online'), status: makeStatus(), ...over }
}

export function makeActions(): CoreActions {
  return {
    patchConfig: vi.fn(),
    downloadVoice: vi.fn(),
    previewVoice: vi.fn(),
    selectVoice: vi.fn(),
    renameDevice: vi.fn(),
    setStages: vi.fn(),
    setDispatcher: vi.fn(),
    restart: vi.fn(),
    loadAccess: vi.fn(),
    setToken: vi.fn(),
    select: vi.fn(),
    selectTurn: vi.fn(),
    dismissNotice: vi.fn(),
  } as unknown as CoreActions
}
