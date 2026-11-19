// Мост Mac-приложения: страница в его окне может попросить открыть файлы ядра в Finder.

/** Что приложение умеет открыть; других действий нет. */
export type BridgeAction = 'openDataFolder' | 'openConfig' | 'revealLog'

type BridgeWindow = {
  smartespBridge?: unknown
  webkit?: { messageHandlers?: { smartesp?: { postMessage(body: unknown): void } } }
}

/** Есть ли мост: страница открыта в окне приложения (оно ставит window.smartespBridge = true). */
export function hasBridge(win: unknown = window): boolean {
  const w = win as BridgeWindow
  return w.smartespBridge === true && typeof w.webkit?.messageHandlers?.smartesp?.postMessage === 'function'
}

/** Просит приложение выполнить действие; без моста ничего не делает. */
export function sendBridge(action: BridgeAction, win: unknown = window): void {
  if (!hasBridge(win)) return
  ;(win as BridgeWindow).webkit?.messageHandlers?.smartesp?.postMessage({ action })
}
