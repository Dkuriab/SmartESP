// Итоги прогонов для таблицы: числа из result.json набора, дата из имени, лучший прогон цели.
import type { TrainRun } from '../../state/trainingActions'

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** «22.11 11:15» из имени прогона «20261122-111546-kuzya». */
export function runDate(name: string): string {
  const m = /^\d{4}(\d{2})(\d{2})-(\d{2})(\d{2})/.exec(name)
  return m ? `${m[2]}.${m[1]} ${m[3]}:${m[4]}` : name
}

/** «узнано 3 из 4» из {total, detected} (или {total, false_wakes}); нет — «—». */
export function ofTotal(v: unknown, key: 'detected' | 'false_wakes'): string {
  if (typeof v !== 'object' || v === null) return '—'
  const total = num((v as Record<string, unknown>).total)
  const part = num((v as Record<string, unknown>)[key])
  return total ? `${part ?? 0} из ${total}` : '—'
}

/** Доля в процентах без дробной части или «—». */
export function percent(v: unknown): string {
  const n = num(v)
  return n === null ? '—' : `${Math.round(n * 100)} %`
}

/** Число с одним знаком или «—». */
export function decimal(v: unknown): string {
  const n = num(v)
  return n === null ? '—' : n.toFixed(n < 10 ? 2 : 1)
}

/** Лучший прогон каждой цели: больше узнанных живых записей, затем выше recall; ложных ≤ 0,5 в час. */
/** a лучше b по очереди признаков. */
function better(a: [number, number, number], b: [number, number, number]): boolean {
  if (a[0] !== b[0]) return a[0] > b[0]
  return a[1] !== b[1] ? a[1] > b[1] : a[2] > b[2]
}

export function bestRuns(runs: TrainRun[]): Set<string> {
  const score = (r: TrainRun): [number, number, number] => {
    const heard = r.real_heard as { total?: number; detected?: number } | undefined
    const share = heard?.total ? (heard.detected ?? 0) / heard.total : 0
    return [(num(r.false_per_hour) ?? 9) <= 0.5 ? 1 : 0, share, num(r.recall) ?? 0]
  }
  const best = new Map<string, TrainRun>()
  for (const run of runs) {
    const target = String(run.target ?? '')
    const current = best.get(target)
    if (!current || better(score(run), score(current))) best.set(target, run)
  }
  return new Set([...best.values()].map((r) => String(r.run)))
}
