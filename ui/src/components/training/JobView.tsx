// Идущий или последний шаг: что делается, ход (полоса и «сколько из скольки»), время, «Стоп», журнал.
import { useEffect, useRef } from 'react'
import type { TrainJob } from '../../state/trainingActions'
import { shortDuration } from '../../state/tasks'

const STATUS: Record<TrainJob['status'], string> = { running: 'идёт', done: 'готово', failed: 'не удалось', cancelled: 'остановлен' }

type Props = { job: TrainJob; title: string; nowMs: number; onStop: () => void }

export default function JobView({ job, title, nowMs, onStop }: Props) {
  const logRef = useRef<HTMLPreElement>(null)
  const running = job.status === 'running'
  const end = job.finished_at ?? nowMs / 1000
  const share = job.total > 0 ? Math.min(100, Math.round((100 * job.done) / job.total)) : null
  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [job.log.length])
  return (
    <div className={`job job-${job.status}`} role="status" aria-label="Ход обучения">
      <div className="job-head">
        <strong>{title}</strong>
        <span>{`${STATUS[job.status]} · ${shortDuration(end - job.started_at)}`}</span>
        {running && <button type="button" className="btn btn-plain" onClick={onStop}>Стоп</button>}
      </div>
      {running && (
        <>
          <div className="job-bar"><div style={{ width: `${share ?? 0}%` }} /></div>
          <div className="set-note">{job.stage ? `${job.stage}: ${job.done} из ${job.total}${share === null ? '' : ` (${share} %)`}` : 'запускается…'}</div>
        </>
      )}
      {job.error && <div className="set-note warn">{job.error}</div>}
      <details className="job-log">
        <summary className="cap">{`Журнал (${job.log.length})`}</summary>
        <pre ref={logRef}>{job.log.join('\n')}</pre>
      </details>
    </div>
  )
}
