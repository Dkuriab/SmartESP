// Раскладка схемы: места, куда пользователь перетащил узлы (по id узла, в браузере),
// и слияние свежих узлов с уже показанными без сброса мест и размеров.
import type { Node, NodeChange, XYPosition } from '@xyflow/react'

export type Positions = Record<string, XYPosition>

export const POSITIONS_KEY = 'smartesp.schema.positions'

/** Хранилище браузера или null: в приватном окне и при запрете даже обращение к нему бросает. */
export function browserStorage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

const isPoint = (v: unknown): v is XYPosition =>
  !!v && typeof v === 'object' && Number.isFinite((v as XYPosition).x) && Number.isFinite((v as XYPosition).y)

/** Сохранённые места; нет хранилища или данные битые — пусто. */
export function loadPositions(storage: Storage | null): Positions {
  try {
    const raw: unknown = JSON.parse(storage?.getItem(POSITIONS_KEY) ?? '{}')
    if (!raw || typeof raw !== 'object') return {}
    const entries = Object.entries(raw as Record<string, unknown>).filter(([, v]) => isPoint(v))
    return Object.fromEntries(entries.map(([id, v]) => [id, { x: (v as XYPosition).x, y: (v as XYPosition).y }]))
  } catch {
    return {}
  }
}

/** Запоминает места; без хранилища молча ничего не делает. */
export function savePositions(storage: Storage | null, positions: Positions): void {
  try {
    storage?.setItem(POSITIONS_KEY, JSON.stringify(positions))
  } catch {
    // без хранилища раскладка живёт до перезагрузки страницы
  }
}

/** «Расставить заново»: забыть все места. */
export function clearPositions(storage: Storage | null): void {
  try {
    storage?.removeItem(POSITIONS_KEY)
  } catch {
    // нечего забывать
  }
}

/**
 * Свежие узлы схемы поверх показанных: место — у тянущегося сейчас его текущее, иначе
 * сохранённое, иначе вычисленное; размеры (measured), измеренные React Flow, сохраняются —
 * без них React Flow прячет узлы и стрелки до нового измерения.
 */
export function mergeNodes(prev: Node[], next: Node[], saved: Positions): Node[] {
  const old = new Map(prev.map((n) => [n.id, n]))
  return next.map((n) => {
    const was = old.get(n.id)
    const position = was?.dragging ? was.position : (saved[n.id] ?? n.position)
    return { ...n, position, measured: was?.measured, dragging: was?.dragging }
  })
}

/** Места после законченных сдвигов (конец перетаскивания, шаг клавишей); нет таких — null. */
export function finishedMoves(saved: Positions, changes: NodeChange[]): Positions | null {
  let next: Positions | null = null
  for (const c of changes) {
    if (c.type !== 'position' || c.dragging || !c.position) continue
    next = { ...(next ?? saved), [c.id]: { x: c.position.x, y: c.position.y } }
  }
  return next
}
