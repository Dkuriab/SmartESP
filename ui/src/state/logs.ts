// Журнал ядра во вкладке «Ядро»: строки копятся пачками, хранится не больше MAX_LOG_LINES.
import { useEffect, useState } from 'react'
import type { LogHandlers, LogLine } from '../api/logs'

/** Сколько последних строк держит интерфейс. */
export const MAX_LOG_LINES = 1000
/** Строки копятся и показываются не чаще, чем раз в столько мс: поток журнала не тормозит экран. */
export const FLUSH_MS = 150
/** Уровни, которые фильтр «Ошибки» оставляет. */
const PROBLEM_LEVELS = new Set(['WARNING', 'ERROR', 'CRITICAL'])

export type LogEntry = LogLine & { id: number }

/** Ошибка или предупреждение. */
export function isProblem(line: LogLine): boolean {
  return PROBLEM_LEVELS.has(line.level)
}

/** Добавляет строки в конец и оставляет последние max. */
export function appendLines(prev: LogEntry[], added: LogEntry[], max = MAX_LOG_LINES): LogEntry[] {
  if (added.length === 0) return prev
  const all = prev.concat(added)
  return all.length > max ? all.slice(all.length - max) : all
}

type Watch = (handlers: LogHandlers) => () => void

/** Строки журнала и есть ли связь; подписка живёт, пока смонтирован вызывающий компонент. */
export function useLogLines(watch: Watch): { lines: LogEntry[]; online: boolean } {
  const [lines, setLines] = useState<LogEntry[]>([])
  const [online, setOnline] = useState(false)
  useEffect(() => {
    let nextId = 0
    let pending: LogEntry[] = []
    let timer: ReturnType<typeof setTimeout> | undefined
    const flush = () => {
      timer = undefined
      const batch = pending
      pending = []
      setLines((prev) => appendLines(prev, batch))
    }
    const stop = watch({
      onLine(line) {
        pending.push({ ...line, id: nextId++ })
        timer ??= setTimeout(flush, FLUSH_MS)
      },
      onOpen() {
        // ядро шлёт последние строки заново: старые копии убираем
        pending = []
        setLines([])
        setOnline(true)
      },
      onClose: () => setOnline(false),
    })
    return () => {
      clearTimeout(timer)
      stop()
    }
  }, [watch])
  return { lines, online }
}
