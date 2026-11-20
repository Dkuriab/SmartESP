// Подгонка схемы под место: при смене набора узлов (key) и при изменении размера области.
// Пока у области нулевой размер (окно скрыто, ещё не разложено), не подгоняем: React Flow
// посчитал бы масштаб для пустого места, и схема ушла бы за край до переключения вкладок.
import { useReactFlow } from '@xyflow/react'
import type { FitViewOptions } from '@xyflow/react'
import { useEffect } from 'react'

/** Пауза после последнего изменения размера, мс. */
const RESIZE_MS = 150

/**
 * Подгонка: не крупнее 1,2 (на широком экране узлы не раздуваются) и не мельче 0,45
 * (подписи читаются; дальше можно отдалить колесом). Сверху место под «Расставить заново».
 */
const FIT: FitViewOptions = { maxZoom: 1.2, minZoom: 0.45, padding: { top: '44px', left: '16px', right: '16px', bottom: '24px' } }

type Props = {
  /** Смена значения — подогнать заново (число узлов, «Расставить заново»). */
  fitKey: string
  width: number
  height: number
}

/** Ставится внутрь ReactFlow; сама ничего не рисует. */
export default function Refit({ fitKey, width, height }: Props) {
  const { fitView } = useReactFlow()
  const ready = width > 0 && height > 0
  useEffect(() => {
    if (ready) void fitView(FIT)
  }, [fitKey, ready, fitView])
  useEffect(() => {
    if (!ready) return
    const timer = setTimeout(() => void fitView(FIT), RESIZE_MS)
    return () => clearTimeout(timer)
  }, [width, height, ready, fitView])
  return null
}
