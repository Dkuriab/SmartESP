// Живая подсветка для схемы: держится не меньше LIVE_MIN_MS и гаснет; без связи — снята сразу.
import { useEffect, useState, useSyncExternalStore } from 'react'
import type { Glow } from '../../schema/linger'
import { createLinger } from '../../schema/linger'
import type { Live } from '../../state/live'

export function useLiveGlow(live: Live, online: boolean): Glow {
  const [linger] = useState(() => createLinger())
  useEffect(() => {
    // после обрыва окончания работы могли потеряться: старую подсветку не держим
    if (online) linger.update(live)
    else linger.clear()
  }, [linger, live, online])
  return useSyncExternalStore(linger.subscribe, linger.snapshot)
}
