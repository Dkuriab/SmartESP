// Обучение из приложения: какую цель обучать, шаги набора («Запустить»), ход идущего шага и прогоны.
import { useCallback, useEffect, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { TrainJob, TrainKit, TrainRun } from '../../state/trainingActions'
import JobView from './JobView'
import RunsTable from './RunsTable'

const POLL_MS = 1000

/** Ход шага: загружается сразу, пока шаг идёт — раз в секунду; кончился — onFinished. */
function useJob(actions: CoreActions, kit: string, onFinished: () => void) {
  const [job, setJob] = useState<TrainJob | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const { loadJob } = actions
  const refresh = useCallback(() => void loadJob(kit).then(setJob), [loadJob, kit])
  useEffect(refresh, [refresh])
  const running = job?.status === 'running'
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      setNowMs(Date.now())
      refresh()
    }, POLL_MS)
    return () => {
      clearInterval(timer)
      onFinished()
    }
  }, [running, refresh, onFinished])
  return { job, setJob, nowMs, running }
}

type Props = { kit: TrainKit; actions: CoreActions }

export default function TrainPanel({ kit, actions }: Props) {
  const [targetId, setTargetId] = useState(kit.targets[0]?.id ?? '')
  const [runs, setRuns] = useState<TrainRun[]>([])
  const { loadRuns } = actions
  const reloadRuns = useCallback(() => void loadRuns(kit.id).then(setRuns), [loadRuns, kit.id])
  useEffect(reloadRuns, [reloadRuns])
  const { job, setJob, nowMs, running } = useJob(actions, kit.id, reloadRuns)
  const target = kit.targets.find((t) => t.id === targetId) ?? kit.targets[0]
  const start = async (step: string, forTarget: boolean, run = '') => {
    const started = await actions.startStep(kit.id, step, forTarget ? (target?.id ?? '') : '', run)
    if (started) setJob(started)
  }
  const stop = async () => {
    await actions.stopJob(kit.id)
    setJob(await actions.loadJob(kit.id))
  }
  const stepTitle = (j: TrainJob) => {
    const title = kit.steps.find((s) => s.id === j.step)?.title ?? j.step
    const goal = kit.targets.find((t) => t.id === j.target)?.title
    return goal ? `${title} · ${goal}` : title
  }
  return (
    <div className="record-panel">
      <div className="cap">Обучение на этом Mac</div>
      <label className="field">
        <span className="lbl">Что обучаем</span>
        <select className="val" value={target?.id ?? ''} disabled={running} onChange={(e) => setTargetId(e.target.value)}>
          {kit.targets.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
        </select>
      </label>
      <ol className="steps">
        {kit.steps.filter((s) => s.id !== 'embed').map((s) => (
          <li key={s.id}>
            <div><strong>{s.title}</strong><div className="set-note">{s.hint}</div></div>
            <button type="button" className="btn" disabled={running} onClick={() => void start(s.id, s.per_target)}>Запустить</button>
          </li>
        ))}
      </ol>
      {job && <JobView job={job} title={stepTitle(job)} nowMs={nowMs} onStop={() => void stop()} />}
      <div className="cap">Прогоны</div>
      <RunsTable runs={runs} busy={running} onEmbed={(run) => void start('embed', false, run)} />
    </div>
  )
}
