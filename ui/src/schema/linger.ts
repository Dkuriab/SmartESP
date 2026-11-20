// Живая подсветка схемы во времени: короткий вызов светится не меньше LIVE_MIN_MS,
// потом плавно гаснет LIVE_FADE_MS. Хранилище для useSyncExternalStore; таймеры — внутри.
import type { Live, LiveExecutor, LiveTool } from '../state/live'
import { NO_LIVE } from '../state/live'

/** Сколько держится живая подсветка, даже если работа длилась миллисекунды, мс. */
export const LIVE_MIN_MS = 1200
/** Сколько гаснет подсветка после конца работы, мс. */
export const LIVE_FADE_MS = 600

/** Что показывать: работающее (с ещё гаснущим) и ключи гаснущего («executor:<id>», «connector:<id>»). */
export type Glow = { live: Live; fading: ReadonlySet<string> }

type Entry = { value: LiveExecutor | LiveTool; since: number; ended?: number }
type Entries = Record<string, Entry>

export const NO_GLOW: Glow = { live: NO_LIVE, fading: new Set() }

/** Когда подсветка начинает гаснуть: не раньше конца работы и не раньше since + минимум. */
const fadeAt = (e: Entry): number => Math.max(e.since + LIVE_MIN_MS, e.ended ?? Infinity)

function current(live: Live): Map<string, LiveExecutor | LiveTool> {
  const now = new Map<string, LiveExecutor | LiveTool>()
  for (const [id, v] of Object.entries(live.executors)) now.set(`executor:${id}`, v)
  for (const [id, v] of Object.entries(live.connectors)) now.set(`connector:${id}`, v)
  return now
}

/** Номера последних стартов по ключу. */
type Seen = Record<string, number>

const seqsOf = (live: Live): Seen => Object.fromEntries(Object.entries(live.started ?? {}).map(([k, s]) => [k, s.seq]))

/**
 * Новые записи по свежей живой подсветке: начавшиеся — с at, кончившиеся — ended = at.
 * Старт, которого ещё не видели (номер вырос), зажигается, даже если работа уже
 * кончилась в том же кадре: тогда запись сразу с ended = at и держится минимум.
 */
function track(entries: Entries, live: Live, at: number, seen: Seen): Entries {
  const now = current(live)
  const next: Entries = {}
  for (const [key, value] of now) {
    const old = entries[key]
    next[key] = { value, since: old && old.ended === undefined ? old.since : at }
  }
  for (const [key, s] of Object.entries(live.started ?? {})) {
    if (s.seq <= (seen[key] ?? 0)) continue
    seen[key] = s.seq
    if (!now.has(key)) next[key] = { value: s.value, since: at, ended: at }
  }
  for (const [key, old] of Object.entries(entries)) {
    if (!(key in next)) next[key] = old.ended === undefined ? { ...old, ended: at } : old
  }
  return next
}

/** Без отгоревших записей. */
function prune(entries: Entries, at: number): Entries {
  return Object.fromEntries(Object.entries(entries).filter(([, e]) => at < fadeAt(e) + LIVE_FADE_MS))
}

function glowOf(entries: Entries, at: number): Glow {
  const live: Live = { executors: {}, connectors: {} }
  const fading = new Set<string>()
  for (const [key, e] of Object.entries(entries)) {
    const [kind, id] = [key.slice(0, key.indexOf(':')), key.slice(key.indexOf(':') + 1)]
    if (kind === 'executor') live.executors[id] = e.value as LiveExecutor
    else live.connectors[id] = e.value as LiveTool
    if (at >= fadeAt(e)) fading.add(key)
  }
  return Object.keys(entries).length === 0 ? NO_GLOW : { live, fading }
}

/** Через сколько мс сменится вид (начнёт гаснуть или пропадёт); null — ничего не ждём. */
function nextChange(entries: Entries, at: number): number | null {
  let next = Infinity
  for (const e of Object.values(entries)) {
    for (const t of [fadeAt(e), fadeAt(e) + LIVE_FADE_MS]) if (t > at) next = Math.min(next, t)
  }
  return Number.isFinite(next) ? next - at : null
}

/**
 * Хранилище живой подсветки; now — часы (подменяются в тестах); initial — живая
 * подсветка на момент создания: её прошлые старты не зажигаются заново (смена вкладки).
 */
export function createLinger(now: () => number = () => Date.now(), initial?: Live) {
  const seen: Seen = initial ? seqsOf(initial) : {}
  let entries: Entries = {}
  let glow: Glow = NO_GLOW
  let timer: ReturnType<typeof setTimeout> | undefined
  const subscribers = new Set<() => void>()

  function schedule(at: number) {
    clearTimeout(timer)
    const wait = nextChange(entries, at)
    if (wait !== null && subscribers.size > 0) timer = setTimeout(refresh, wait)
  }
  function refresh() {
    const at = now()
    entries = prune(entries, at)
    glow = glowOf(entries, at)
    subscribers.forEach((notify) => notify())
    schedule(at)
  }
  return {
    /** Свежая живая подсветка из состояния. */
    update(live: Live) {
      entries = track(entries, live, now(), seen)
      refresh()
    },
    /** Обрыв связи: снять всё сразу, без задержки и угасания. */
    clear() {
      entries = {}
      refresh()
    },
    subscribe(notify: () => void) {
      subscribers.add(notify)
      schedule(now())
      return () => {
        subscribers.delete(notify)
        if (subscribers.size === 0) clearTimeout(timer)
      }
    },
    snapshot: (): Glow => glow,
  }
}

export type Linger = ReturnType<typeof createLinger>
