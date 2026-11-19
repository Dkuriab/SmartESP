// Подгонка схемы под место: при смене числа узлов и при изменении размера окна.
import { useReactFlow } from '@xyflow/react'
import { useEffect } from 'react'

/** Пауза после последнего изменения размера окна, мс. */
const RESIZE_MS = 150

/** Ставится внутрь ReactFlow; сама ничего не рисует. */
export default function Refit({ count }: { count: number }) {
  const { fitView } = useReactFlow()
  useEffect(() => {
    void fitView()
  }, [count, fitView])
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const onResize = () => {
      clearTimeout(timer)
      timer = setTimeout(() => void fitView(), RESIZE_MS)
    }
    window.addEventListener('resize', onResize)
    return () => {
      clearTimeout(timer)
      window.removeEventListener('resize', onResize)
    }
  }, [fitView])
  return null
}
