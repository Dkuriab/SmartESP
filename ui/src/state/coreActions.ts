// Действия вкладки «Ядро»: сведения, остановка, выгрузка моделей, журнал, мост приложения.
import type { BridgeAction } from '../api/bridge'
import { sendBridge } from '../api/bridge'
import type { LogHandlers } from '../api/logs'
import { connectLogs } from '../api/logs'
import type { components } from '../api/schema'
import type { Client } from './actions'
import type { Dispatch } from './request'
import { send, sendNotify } from './request'

export type CoreInfo = components['schemas']['CoreInfoOut']

export type CoreTabActions = {
  /** Версия, время работы, порт, папка данных; ошибка — null. */
  loadCoreInfo(): Promise<CoreInfo | null>
  /** Честная остановка ядра (без перезапуска); true — ядро приняло просьбу. */
  stopCore(): Promise<boolean>
  /** Выгрузить модель из памяти Ollama; удалось — модель пропадает из status и уведомление. */
  unloadModel(name: string): Promise<void>
  /** Подписка на журнал ядра; возвращает отключение. */
  watchLogs(handlers: LogHandlers): () => void
  /** Просьба к Mac-приложению (только при мосте). */
  openInApp(action: BridgeAction): void
}

export function createCoreActions(client: Client, dispatch: Dispatch, token: string): CoreTabActions {
  return {
    async loadCoreInfo() {
      const outcome = await send(dispatch, () => client.GET('/api/v1/core'))
      return outcome.ok ? outcome.data : null
    },
    async stopCore() {
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/core/stop'))
      return outcome.ok
    },
    async unloadModel(name) {
      const outcome = await sendNotify(dispatch, () => client.POST('/api/v1/models/unload', { body: { name } }))
      if (!outcome.ok) return
      dispatch({ type: 'modelUnloaded', name })
      dispatch({ type: 'notice', notice: { text: `Модель ${name} выгружена`, tone: 'ok' } })
    },
    watchLogs(handlers) {
      const conn = connectLogs(token, handlers)
      return () => conn.close()
    },
    openInApp: (action) => sendBridge(action),
  }
}
