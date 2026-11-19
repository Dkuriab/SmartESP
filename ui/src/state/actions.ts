// Действия интерфейса: запросы к ядру. Ошибки становятся уведомлениями.
import type { createClient } from '../api/client'
import type { CoreTabActions } from './coreActions'
import { createCoreActions } from './coreActions'
import type { ExecutorActions } from './executorActions'
import { createExecutorActions } from './executorActions'
import type { FileActions } from './fileActions'
import { createFileActions } from './fileActions'
import type { Config, Notice, Selection } from './model'
import type { Dispatch } from './request'
import { send, sendNotify } from './request'
import type { SentExecutors } from './sentExecutors'
import { createSentExecutors } from './sentExecutors'

export type Client = ReturnType<typeof createClient>

/** Обработчик в списке stages (форма config.yaml). */
export type StageEntry = { kind: string; timeout_ms?: number }

export type CoreActions = ExecutorActions &
  FileActions &
  CoreTabActions & {
  /** Частичная правка настроек; description показывается, пока она применяется. */
  patchConfig(patch: Record<string, unknown>, description: string): Promise<void>
  downloadVoice(kind: string, voice: string): Promise<void>
  /** Образец голоса (WAV). Ошибка — уведомление и отказ промиса. */
  previewVoice(kind: string, voice: string, style: string): Promise<Blob>
  selectVoice(kind: string, voice: string): Promise<void>
  renameDevice(id: string, name: string): Promise<void>
  setStages(list: StageEntry[]): Promise<void>
  /** Записи connectors по id (ядро сливает их с настройками); description — что меняется. */
  setConnectors(list: Array<Record<string, unknown>>, description: string): Promise<void>
  restart(): Promise<void>
  /** Адреса для входа из сети; ошибка — пустой список. */
  loadAccess(): Promise<string[]>
  setToken(token: string): void
  /** Выбор на схеме или в списке (null — снять). */
  select(selected: Selection | null): void
  /** Выбор хода в ленте (null — снять). */
  selectTurn(turnId: number | string | null): void
  dismissNotice(): void
  /** Показать уведомление (ошибка в самом браузере, без запроса к ядру). */
  showNotice(notice: Notice): void
}

export type ActionDeps = {
  client: Client
  dispatch: Dispatch
  /** Текущие настройки (нужны config.effective.executors); null — не загружены. */
  getConfig: () => Config | null
  /** Новый токен: сохранить и переподключиться. */
  onToken: (token: string) => void
  /** Токен клиента: им подключается журнал (WebSocket). */
  token: string
  /**
   * Действия вкладки «Ядро». Живут дольше самих действий, чтобы подписка на журнал не
   * переподключалась с каждыми настройками; по умолчанию — свои, с token.
   */
  coreTab?: CoreTabActions
  /** Часы, мс (в тестах — поддельные). */
  now?: () => number
  /**
   * Отправленные, но ещё не перечитанные исполнители. Живёт дольше самих действий
   * (они пересоздаются с каждыми настройками) и видит события и загрузки; по умолчанию — свои.
   */
  sentExecutors?: SentExecutors
}

/** Просьба о перезапуске: кнопка ждёт переподключения; отказ снова открывает её. */
async function restartCore(client: Client, dispatch: Dispatch): Promise<void> {
  dispatch({ type: 'restarting', on: true })
  const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/restart'))
  if (!outcome.ok) dispatch({ type: 'restarting', on: false })
}

/** Создаёт действия поверх клиента; в тестах клиент поддельный. */
export function createActions(deps: ActionDeps): CoreActions {
  const { client, dispatch, getConfig, onToken, now = Date.now } = deps

  /** PATCH настроек; change_id принятой правки или null. */
  async function sendPatch(patch: Record<string, unknown>, description: string): Promise<number | null> {
    const outcome = await sendNotify(dispatch, () => client.PATCH('/api/v1/config', { body: patch }))
    if (!outcome.ok) return null
    dispatch({ type: 'changeSent', changeId: outcome.data.change_id, description, at: now() })
    return outcome.data.change_id
  }
  const patch = async (body: Record<string, unknown>, description: string) => {
    await sendPatch(body, description)
  }

  async function previewVoice(kind: string, voice: string, style: string): Promise<Blob> {
    const outcome = await sendNotify(dispatch, () =>
      client.POST('/api/v1/voices/preview', { body: { kind, voice, style }, parseAs: 'blob' }),
    )
    if (!outcome.ok) throw new Error(outcome.text || 'Нет доступа')
    return outcome.data
  }

  async function loadAccess(): Promise<string[]> {
    const outcome = await send(dispatch, () => client.GET('/api/v1/access'))
    return outcome.ok ? outcome.data.urls : []
  }

  const sent = deps.sentExecutors ?? createSentExecutors(now)
  return {
    ...createExecutorActions({ dispatch, getConfig, sent }, sendPatch),
    ...createFileActions(client, dispatch),
    ...(deps.coreTab ?? createCoreActions(client, dispatch, deps.token)),
    patchConfig: patch,
    previewVoice,
    loadAccess,
    async downloadVoice(kind, voice) {
      dispatch({ type: 'downloadRequested', kind, voice })
      await sendNotify(dispatch, () => client.POST('/api/v1/voices/download', { body: { kind, voice } }))
    },
    selectVoice: (kind, voice) => patch({ tts: { kind, voice } }, `Голос ${voice}`),
    renameDevice: (id, name) => patch({ devices: { [id]: { name } } }, `Имя колонки: ${name}`),
    setStages: (list) => patch({ stages: list }, 'Обработчики'),
    setConnectors: (list, description) => patch({ connectors: list }, description),
    restart: () => restartCore(client, dispatch),
    setToken: onToken,
    select: (selected) => dispatch({ type: 'select', selected }),
    selectTurn: (turnId) => dispatch({ type: 'selectTurn', turnId }),
    dismissNotice: () => dispatch({ type: 'dismissNotice' }),
    showNotice: (notice) => dispatch({ type: 'notice', notice }),
  }
}
