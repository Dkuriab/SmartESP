// Действия интерфейса: запросы к ядру. Ошибки становятся уведомлениями.
import type { createClient } from '../api/client'
import type { Config } from './model'
import type { Dispatch } from './request'
import { send, sendNotify } from './request'

export type Client = ReturnType<typeof createClient>

/** Обработчик в списке stages (форма config.yaml). */
export type StageEntry = { kind: string; timeout_ms?: number }

/** Правка входного исполнителя (диспетчера). */
export type DispatcherPatch = { model?: string; system_prompt?: string }

export type CoreActions = {
  /** Частичная правка настроек; description показывается, пока она применяется. */
  patchConfig(patch: Record<string, unknown>, description: string): Promise<void>
  downloadVoice(kind: string, voice: string): Promise<void>
  /** Образец голоса (WAV). Ошибка — уведомление и отказ промиса. */
  previewVoice(kind: string, voice: string, style: string): Promise<Blob>
  selectVoice(kind: string, voice: string): Promise<void>
  renameDevice(id: string, name: string): Promise<void>
  setStages(list: StageEntry[]): Promise<void>
  setDispatcher(patch: DispatcherPatch): Promise<void>
  restart(): Promise<void>
  /** Адреса для входа из сети; ошибка — пустой список. */
  loadAccess(): Promise<string[]>
  setToken(token: string): void
}

export type ActionDeps = {
  client: Client
  dispatch: Dispatch
  /** Текущие настройки (нужны config.effective.executors); null — не загружены. */
  getConfig: () => Config | null
  /** Новый токен: сохранить и переподключиться. */
  onToken: (token: string) => void
}

type Executor = Record<string, unknown> & { entry?: unknown }

/** Список executors с правкой у входного; null — настроек ещё нет. */
function patchedExecutors(config: Config | null, patch: DispatcherPatch): Executor[] | null {
  const list = config?.effective.executors
  if (!Array.isArray(list)) return null
  const executors = list.filter((e): e is Executor => typeof e === 'object' && e !== null)
  if (!executors.some((e) => e.entry === true)) return null
  return executors.map((e) => (e.entry === true ? { ...e, ...patch } : e))
}

/** Создаёт действия поверх клиента; в тестах клиент поддельный. */
export function createActions({ client, dispatch, getConfig, onToken }: ActionDeps): CoreActions {
  async function patchConfig(patch: Record<string, unknown>, description: string) {
    const outcome = await sendNotify(dispatch, () => client.PATCH('/api/v1/config', { body: patch }))
    if (outcome.ok) dispatch({ type: 'changeSent', changeId: outcome.data.change_id, description })
  }

  async function previewVoice(kind: string, voice: string, style: string): Promise<Blob> {
    const outcome = await sendNotify(dispatch, () =>
      client.POST('/api/v1/voices/preview', { body: { kind, voice, style }, parseAs: 'blob' }),
    )
    if (!outcome.ok) throw new Error(outcome.text || 'Нет доступа')
    return outcome.data
  }

  async function setDispatcher(patch: DispatcherPatch) {
    const executors = patchedExecutors(getConfig(), patch)
    if (!executors) {
      dispatch({ type: 'notice', notice: { text: 'Настройки ещё не загружены', tone: 'error' } })
      return
    }
    await patchConfig({ executors }, 'Диспетчер')
  }

  async function loadAccess(): Promise<string[]> {
    const outcome = await send(dispatch, () => client.GET('/api/v1/access'))
    return outcome.ok ? outcome.data.urls : []
  }

  return {
    patchConfig,
    previewVoice,
    setDispatcher,
    loadAccess,
    async downloadVoice(kind, voice) {
      await sendNotify(dispatch, () => client.POST('/api/v1/voices/download', { body: { kind, voice } }))
    },
    selectVoice: (kind, voice) => patchConfig({ tts: { kind, voice } }, `Голос ${voice}`),
    renameDevice: (id, name) => patchConfig({ devices: { [id]: { name } } }, `Имя колонки: ${name}`),
    setStages: (list) => patchConfig({ stages: list }, 'Обработчики'),
    async restart() {
      await sendNotify(dispatch, () => client.POST('/api/v1/restart'))
    },
    setToken: onToken,
  }
}
