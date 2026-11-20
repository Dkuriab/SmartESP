import type { Node, NodeChange } from '@xyflow/react'
import { describe, expect, it } from 'vitest'
import { POSITIONS_KEY, clearPositions, finishedMoves, loadPositions, mergeNodes, savePositions } from './layout'

const node = (id: string, x: number, label = id): Node => ({ id, type: 'device', position: { x, y: 0 }, data: { label } })

function fakeStorage(): Storage {
  const data: Record<string, string> = {}
  return {
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => void (data[k] = v),
    removeItem: (k: string) => void delete data[k],
  } as unknown as Storage
}

const broken = {
  getItem: () => {
    throw new Error('denied')
  },
  setItem: () => {
    throw new Error('denied')
  },
  removeItem: () => {
    throw new Error('denied')
  },
} as unknown as Storage

describe('раскладка: место узлов в браузере', () => {
  it('сохраняет и читает места по id узла', () => {
    const storage = fakeStorage()
    savePositions(storage, { 'device:a': { x: 10, y: 20 } })
    expect(loadPositions(storage)).toEqual({ 'device:a': { x: 10, y: 20 } })
    clearPositions(storage)
    expect(loadPositions(storage)).toEqual({})
  })

  it('битые и чужие данные не ломают: пусто, неверные записи отброшены', () => {
    const storage = fakeStorage()
    storage.setItem(POSITIONS_KEY, '{oops')
    expect(loadPositions(storage)).toEqual({})
    storage.setItem(POSITIONS_KEY, JSON.stringify({ a: { x: 1, y: 2 }, b: { x: 'no' }, c: null }))
    expect(loadPositions(storage)).toEqual({ a: { x: 1, y: 2 } })
  })

  it('без хранилища (нет или запрещено) — работает без запоминания', () => {
    for (const storage of [null, broken]) {
      expect(loadPositions(storage)).toEqual({})
      expect(() => savePositions(storage, { a: { x: 1, y: 1 } })).not.toThrow()
      expect(() => clearPositions(storage)).not.toThrow()
    }
  })
})

describe('mergeNodes: свежие данные не сбрасывают раскладку', () => {
  it('новый узел — на вычисленном месте; сохранённый — на своём', () => {
    const merged = mergeNodes([], [node('a', 0), node('b', 100)], { b: { x: 500, y: 50 } })
    expect(merged.map((n) => n.position)).toEqual([{ x: 0, y: 0 }, { x: 500, y: 50 }])
  })

  it('размеры, измеренные React Flow, переживают обновление данных', () => {
    const prev = [{ ...node('a', 0), measured: { width: 200, height: 50 } }]
    const a = mergeNodes(prev, [node('a', 0, 'Кухня 2')], {})[0]
    expect(a?.measured).toEqual({ width: 200, height: 50 })
    expect(a?.data.label).toBe('Кухня 2')
  })

  it('узел, который сейчас тянут, остаётся под мышью', () => {
    const prev = [{ ...node('a', 0), position: { x: 333, y: 44 }, dragging: true }]
    const a = mergeNodes(prev, [node('a', 0)], {})[0]
    expect(a?.position).toEqual({ x: 333, y: 44 })
    expect(a?.dragging).toBe(true)
  })

  it('пропавший узел уходит', () => {
    expect(mergeNodes([node('a', 0), node('b', 0)], [node('a', 0)], {}).map((n) => n.id)).toEqual(['a'])
  })
})

describe('finishedMoves: что запомнить', () => {
  it('конец перетаскивания и шаг клавишей запоминаются, ход перетаскивания — нет', () => {
    const during: NodeChange = { type: 'position', id: 'a', position: { x: 1, y: 2 }, dragging: true }
    const done: NodeChange = { type: 'position', id: 'b', position: { x: 3, y: 4 }, dragging: false }
    const size: NodeChange = { type: 'dimensions', id: 'c', dimensions: { width: 1, height: 1 } }
    expect(finishedMoves({ z: { x: 0, y: 0 } }, [during, done, size])).toEqual({ z: { x: 0, y: 0 }, b: { x: 3, y: 4 } })
    expect(finishedMoves({}, [during, size])).toBeNull()
  })
})
