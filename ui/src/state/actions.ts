// Действия интерфейса: запросы к ядру. Ошибки становятся уведомлениями.
import type { createClient } from '../api/client'
import type { Config, Notice, Selection } from './model'
import type { Dispatch } from './request'
import type { Executor, ExecutorPatch } from './executors'
import { executorsOf, withAdded, withLink, withRemoved, withUpdated } from './executors'
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
  /** Новый исполнитель executor-N с моделью входного. */
  addExecutor(): Promise<void>
  updateExecutor(id: string, patch: ExecutorPatch): Promise<void>
  /** Убирает исполнителя и ссылки на него; входного убрать нельзя. */
  removeExecutor(id: string): Promise<void>
  /** Включает/выключает связь from → to; when — условие передачи. */
  setLink(from: string, to: string, enabled: boolean, when: string): Promise<void>
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
  /** Часы, мс (в тестах — поддельные). */
  now?: () => number
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
  async function patchConfig(patch: Record<string, unknown>, description: string) {
    const outcome = await sendNotify(dispatch, () => client.PATCH('/api/v1/config', { body: patch }))
    if (!outcome.ok) return
    dispatch({ type: 'changeSent', changeId: outcome.data.change_id, description, at: now() })
  }

  async function previewVoice(kind: string, voice: string, style: string): Promise<Blob> {
    const outcome = await sendNotify(dispatch, () =>
      client.POST('/api/v1/voices/preview', { body: { kind, voice, style }, parseAs: 'blob' }),
    )
    if (!outcome.ok) throw new Error(outcome.text || 'Нет доступа')
    return outcome.data
  }

  /** Шлёт весь список executors после правки; настроек ещё нет — уведомление. */
  async function changeExecutors(change: (list: Executor[]) => Executor[], description: string) {
    const list = executorsOf(getConfig()?.effective)
    if (!list) {
      dispatch({ type: 'notice', notice: { text: 'Настройки ещё не загружены', tone: 'error' } })
      return
    }
    await patchConfig({ executors: change(list) }, description)
  }

  const updateExecutor = (id: string, patch: ExecutorPatch) =>
    changeExecutors((list) => withUpdated(list, id, patch), 'Исполнитель')

  function setDispatcher(patch: DispatcherPatch) {
    const entry = executorsOf(getConfig()?.effective)?.find((e) => e.entry === true)
    return changeExecutors(
      (list) => withUpdated(list, String(entry?.id), { model: patch.model, systemPrompt: patch.system_prompt }),
      'Диспетчер',
    )
  }

  async function loadAccess(): Promise<string[]> {
    const outcome = await send(dispatch, () => client.GET('/api/v1/access'))
    return outcome.ok ? outcome.data.urls : []
  }

  return {
    patchConfig,
    previewVoice,
    setDispatcher,
    updateExecutor,
    addExecutor: () => changeExecutors(withAdded, 'Новый исполнитель'),
    removeExecutor: (id) => changeExecutors((list) => withRemoved(list, id), 'Исполнитель удалён'),
    setLink: (from, to, enabled, when) =>
      changeExecutors((list) => withLink(list, from, to, enabled, when), 'Связь исполнителей'),
    loadAccess,
    async downloadVoice(kind, voice) {
      dispatch({ type: 'downloadRequested', kind, voice })
      await sendNotify(dispatch, () => client.POST('/api/v1/voices/download', { body: { kind, voice } }))
    },
    selectVoice: (kind, voice) => patchConfig({ tts: { kind, voice } }, `Голос ${voice}`),
    renameDevice: (id, name) => patchConfig({ devices: { [id]: { name } } }, `Имя колонки: ${name}`),
    setStages: (list) => patchConfig({ stages: list }, 'Обработчики'),
    restart: () => restartCore(client, dispatch),
    setToken: onToken,
    select: (selected) => dispatch({ type: 'select', selected }),
    selectTurn: (turnId) => dispatch({ type: 'selectTurn', turnId }),
    dismissNotice: () => dispatch({ type: 'dismissNotice' }),
    showNotice: (notice) => dispatch({ type: 'notice', notice }),
  }
}
