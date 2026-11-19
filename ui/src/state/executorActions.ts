// Действия над исполнителями: каждая правка шлёт весь список executors.
// База правки — последний отправленный список (см. sentExecutors), иначе настройки.
import type { Executor, ExecutorPatch } from './executors'
import { executorsOf, nextExecutorId, withAdded, withLink, withRemoved, withUpdated } from './executors'
import type { Config } from './model'
import type { Dispatch } from './request'
import type { SentExecutors } from './sentExecutors'

export type ExecutorActions = {
  /** Новый исполнитель executor-N с моделью входного; его id, если правка принята, иначе null. */
  addExecutor(): Promise<string | null>
  updateExecutor(id: string, patch: ExecutorPatch): Promise<void>
  /** Убирает исполнителя и ссылки на него; входной и неизвестный — ничего не шлёт. */
  removeExecutor(id: string): Promise<void>
  /** Включает/выключает связь from → to; when — условие передачи. На себя и с неизвестным — ничего не шлёт. */
  setLink(from: string, to: string, enabled: boolean, when: string): Promise<void>
}

export type ExecutorDeps = {
  dispatch: Dispatch
  getConfig: () => Config | null
  sent: SentExecutors
}

/** PATCH настроек; change_id принятой правки или null. */
export type SendPatch = (patch: Record<string, unknown>, description: string) => Promise<number | null>

export function createExecutorActions({ dispatch, getConfig, sent }: ExecutorDeps, sendPatch: SendPatch): ExecutorActions {
  const current = () => sent.base() ?? executorsOf(getConfig()?.effective)

  /**
   * Шлёт весь список после правки; true — правка принята.
   * Настроек ещё нет — уведомление; правка ничего не меняет (тот же список) — ничего не шлёт.
   */
  async function change(edit: (list: Executor[]) => Executor[], description: string): Promise<boolean> {
    const list = current()
    if (!list) {
      dispatch({ type: 'notice', notice: { text: 'Настройки ещё не загружены', tone: 'error' } })
      return false
    }
    const next = edit(list)
    if (next === list) return false
    sent.sending(next)
    const id = await sendPatch({ executors: next }, description)
    if (id === null) sent.clear()
    else sent.accepted(id)
    return id !== null
  }

  return {
    async addExecutor() {
      const id = nextExecutorId(current() ?? [])
      return (await change(withAdded, 'Новый исполнитель')) ? id : null
    },
    async updateExecutor(id, patch) {
      await change((list) => withUpdated(list, id, patch), 'Исполнитель')
    },
    async removeExecutor(id) {
      await change((list) => withRemoved(list, id), 'Исполнитель удалён')
    },
    async setLink(from, to, enabled, when) {
      await change((list) => withLink(list, from, to, enabled, when), 'Связь исполнителей')
    },
  }
}
