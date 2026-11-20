// Размер элемента по ResizeObserver: область схемы меняется не только с окном
// (узкий экран, панели, окно приложения скрыто — тогда 0×0). Без ResizeObserver —
// getBoundingClientRect при монтировании и при изменении размера окна.
import { useEffect, useState } from 'react'

export type BoxSize = { width: number; height: number }

const ZERO: BoxSize = { width: 0, height: 0 }

/** Подписка на размер элемента; report получает целые пиксели. Возвращает отписку. */
function watch(element: HTMLElement, report: (width: number, height: number) => void): () => void {
  if (typeof ResizeObserver === 'undefined') {
    const measure = () => {
      const box = element.getBoundingClientRect()
      report(Math.round(box.width), Math.round(box.height))
    }
    const first = setTimeout(measure, 0)
    window.addEventListener('resize', measure)
    return () => {
      clearTimeout(first)
      window.removeEventListener('resize', measure)
    }
  }
  const observer = new ResizeObserver((entries) => {
    const box = entries[entries.length - 1]?.contentRect
    if (box) report(Math.round(box.width), Math.round(box.height))
  })
  observer.observe(element)
  return () => observer.disconnect()
}

/** Размер элемента; пока не измерен — 0×0. */
export function useBoxSize(element: HTMLElement | null): BoxSize {
  const [size, setSize] = useState<BoxSize>(ZERO)
  useEffect(() => {
    if (!element) return
    return watch(element, (width, height) =>
      setSize((old) => (old.width === width && old.height === height ? old : { width, height })),
    )
  }, [element])
  return size
}
