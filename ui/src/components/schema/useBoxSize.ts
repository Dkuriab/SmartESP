// Размер элемента по ResizeObserver: область схемы меняется не только с окном
// (узкий экран, панели, окно приложения скрыто — тогда 0×0).
import { useEffect, useState } from 'react'

export type BoxSize = { width: number; height: number }

const ZERO: BoxSize = { width: 0, height: 0 }

/** Размер элемента; пока не измерен или без ResizeObserver — 0×0. */
export function useBoxSize(element: HTMLElement | null): BoxSize {
  const [size, setSize] = useState<BoxSize>(ZERO)
  useEffect(() => {
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const box = entries[entries.length - 1]?.contentRect
      if (!box) return
      const width = Math.round(box.width)
      const height = Math.round(box.height)
      setSize((old) => (old.width === width && old.height === height ? old : { width, height }))
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [element])
  return size
}
