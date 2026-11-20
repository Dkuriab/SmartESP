// Живая подсветка для схемы и левого списка: каждый старт работы держится не меньше
// LIVE_MIN_MS (даже если конец пришёл в том же кадре) и гаснет; без связи — снята сразу.
import { useEffect, useState, useSyncExternalStore } from 'react'
import type { Glow } from '../../schema/linger'
import { createLinger } from '../../schema/linger'
import type { Live } from '../../state/live'

export function useLiveGlow(live: Live, online: boolean): Glow {
  // старты, бывшие до монтирования (смена вкладки), заново не зажигаются
  const [linger] = useState(() => createLinger(undefined, live))
  useEffect(() => {
    // после обрыва окончания работы могли потеряться: старую подсветку не держим
    if (online) linger.update(live)
    else linger.clear()
  }, [linger, live, online])
  return useSyncExternalStore(linger.subscribe, linger.snapshot)
}

/** Только горящее (без гаснущего): для точек «работает сейчас» в списке. */
export function steadyLive(glow: Glow): Live {
  const keep = <T,>(kind: string, map: Record<string, T>) =>
    Object.fromEntries(Object.entries(map).filter(([id]) => !glow.fading.has(`${kind}:${id}`)))
  return { executors: keep('executor', glow.live.executors), connectors: keep('connector', glow.live.connectors) }
}
