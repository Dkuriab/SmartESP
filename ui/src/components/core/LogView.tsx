// Живой журнал ядра: фильтр «Ошибки / Всё», прокрутка за новыми строками; прокрутил вверх — пауза.
import { memo, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { LogEntry } from '../../state/logs'
import { isProblem } from '../../state/logs'

/** Ближе к низу, чем на столько пикселей, — считаем, что журнал «у последних строк». */
const BOTTOM_SLACK = 24

type Props = { lines: LogEntry[]; online: boolean }
type Filter = 'problems' | 'all'

const FILTERS: Array<[Filter, string]> = [
  ['problems', 'Ошибки'],
  ['all', 'Всё'],
]

/** Прокрутка за новыми строками, пока пользователь сам не прокрутил вверх. */
function useFollow(key: unknown) {
  const box = useRef<HTMLDivElement>(null)
  const [follow, setFollow] = useState(true)
  useLayoutEffect(() => {
    const el = box.current
    if (follow && el) el.scrollTop = el.scrollHeight
  }, [key, follow])
  const onScroll = () => {
    const el = box.current
    if (el) setFollow(el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_SLACK)
  }
  return { box, follow, onScroll, resume: () => setFollow(true) }
}

/** memo: опрос status и события перерисовывают вкладку, а журнал — до 1000 строк. */
export default memo(function LogView({ lines, online }: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  // тот же массив, пока строки не менялись: иначе прокрутка срабатывала бы на каждой отрисовке
  const shown = useMemo(() => (filter === 'all' ? lines : lines.filter(isProblem)), [lines, filter])
  const { box, follow, onScroll, resume } = useFollow(shown)
  return (
    <section className="core-log" aria-label="Журнал">
      <div className="core-log-head">
        <span className="cap">Журнал{online ? '' : ' · нет связи'}</span>
        <div className="core-filter" role="group" aria-label="Фильтр журнала">
          {FILTERS.map(([id, label]) => (
            <button key={id} type="button" aria-pressed={filter === id} className={`seg${filter === id ? ' on' : ''}`} onClick={() => setFilter(id)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {/* tabIndex: в Safari и WKWebView прокрутка иначе недоступна с клавиатуры; журнал не зачитывается */}
      <div className="core-log-lines" ref={box} onScroll={onScroll} data-testid="log-lines" tabIndex={0} role="log" aria-live="off" aria-label="Строки журнала">
        {shown.length === 0 && <div className="empty">{filter === 'all' ? 'Журнал пуст' : 'Ошибок нет'}</div>}
        {shown.map((line) => (
          <pre key={line.id} className={`core-line level-${line.level.toLowerCase()}`}>
            {line.text}
          </pre>
        ))}
      </div>
      {!follow && (
        <button type="button" className="btn small core-resume" onClick={resume}>
          К последним строкам
        </button>
      )}
    </section>
  )
})
