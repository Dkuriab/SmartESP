// Общие данные для тестов компонентов: состояние ядра и поддельные действия.
import { vi } from 'vitest'
import type { CoreActions } from '../state/actions'
import type { Config, CoreState, Status, Turn, Voice } from '../state/model'
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
    at: 1700000000,
    path: [],
    delegations: [],
    tools: [],
    origin: 'wake',
    source: '',
    person: '',
    kind: 'turn',
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
      { device_id: 'a', name: 'Кухня', connected: true, remote: '', fw: '', protocol: 2, volume: 50 },
      { device_id: 'b', name: 'Спальня', connected: false, remote: '', fw: '', protocol: 2, volume: 50 },
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

export function makeConfig(effective: Record<string, unknown> = {}): Config {
  return {
    effective: {
      stages: [{ kind: 'whisper_detect', timeout_ms: 50 }],
      executors: [
        { id: 'dispatcher', entry: true, model: 'qwen3', system_prompt: 'Отвечай коротко' },
        { id: 'big', entry: false, model: 'gpt-oss' },
      ],
      tts: { kind: 'piper', voice: 'irina' },
      ...effective,
    },
    overridden: [],
    restart_sections: [],
    dispatcher_prompt: 'Отвечай коротко\nПравило шёпота',
    executor_prompts: {},
  }
}

export function makeVoice(over: Partial<Voice> = {}): Voice {
  return { kind: 'piper', voice: 'irina', title: 'Ирина', size_mb: 60, downloaded: true, current: false, ...over }
}

export function makeActions(): CoreActions {
  return {
    patchConfig: vi.fn(),
    downloadVoice: vi.fn(),
    previewVoice: vi.fn(),
    selectVoice: vi.fn(),
    renameDevice: vi.fn(),
    playFile: vi.fn(),
    stopFile: vi.fn(),
    setStages: vi.fn(),
    setConnectors: vi.fn(),
    saveConnectorEnv: vi.fn().mockResolvedValue(''),
    addExecutor: vi.fn().mockResolvedValue(null),
    updateExecutor: vi.fn(),
    removeExecutor: vi.fn(),
    setLink: vi.fn(),
    restart: vi.fn(),
    loadAccess: vi.fn().mockResolvedValue([]),
    loadTraining: vi.fn().mockResolvedValue([]),
    saveTargets: vi.fn().mockResolvedValue(null),
    recordPhrase: vi.fn(),
    listRecordings: vi.fn().mockResolvedValue([]),
    fetchRecording: vi.fn().mockResolvedValue(null),
    deleteRecording: vi.fn().mockResolvedValue(true),
    startStep: vi.fn().mockResolvedValue(null),
    loadJob: vi.fn().mockResolvedValue(null),
    stopJob: vi.fn(),
    loadRuns: vi.fn().mockResolvedValue([]),
    installRun: vi.fn().mockResolvedValue(true),
    installFirmware: vi.fn().mockResolvedValue(true),
    loadCloudModels: vi.fn().mockResolvedValue([]),
    setCloudKey: vi.fn(),
    setToken: vi.fn(),
    select: vi.fn(),
    selectTurn: vi.fn(),
    dismissNotice: vi.fn(),
    showNotice: vi.fn(),
    loadCoreInfo: vi.fn().mockResolvedValue(null),
    stopCore: vi.fn().mockResolvedValue(true),
    unloadModel: vi.fn().mockResolvedValue(undefined),
    watchLogs: vi.fn(() => () => {}),
    openInApp: vi.fn(),
  } as unknown as CoreActions
}
