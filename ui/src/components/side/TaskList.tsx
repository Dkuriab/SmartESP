// «В работе»: что ядро и коннекторы делают в фоне — что, откуда/для кого, сколько идёт и когда ждать.
// Законченная задача ещё немного видна с итогом и угасает.
import { useEffect, useState } from 'react'
import type { Task } from '../../state/model'
import { fading, sourceLabel, taskTiming, visibleTasks } from '../../state/tasks'

type Props = {
  tasks: Task[]
  /** Имя коннектора по id (нет — показываем id). */
  connectorName: (id: string) => string | undefined
}

const ICONS: Record<Task['status'], string> = { running: '⏳', done: '✅', failed: '⚠️', cancelled: '✖️' }
const TICK_MS = 1_000

/** Текущее время (мс), обновляется раз в секунду, пока on. */
function useNow(on: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!on) return
    const timer = setInterval(() => setNow(Date.now()), TICK_MS)
    return () => clearInterval(timer)
  }, [on])
  return now
}

/** Кто и где: колонка и человек задачи через «·». */
function who(task: Task): string {
  return [task.device_name || task.device_id, task.person].filter(Boolean).join(' · ')
}

function TaskRow({ task, now, connectorName }: { task: Task; now: number } & Pick<Props, 'connectorName'>) {
  const place = [sourceLabel(task.source, connectorName), who(task)].filter(Boolean).join(' · ')
  const title = task.result ? `${task.title}\n${task.result}` : task.title
  return (
    <li className={`task ${task.status}${fading(task, now) ? ' fade' : ''}`} title={title}>
      <span className="ico" aria-hidden="true">
        {ICONS[task.status]}
      </span>
      <span className="task-body">
        <span className="row-label">{task.title}</span>
        <span className="task-sub">{place}</span>
        <span className="task-sub">{taskTiming(task, now)}</span>
      </span>
    </li>
  )
}

export default function TaskList({ tasks, connectorName }: Props) {
  const now = useNow(tasks.length > 0)
  const shown = visibleTasks(tasks, now)
  if (shown.length === 0) return null
  const running = shown.filter((t) => t.status === 'running').length
  return (
    <section aria-label="В работе">
      <div className="sec cap">{running > 0 ? `В работе ${running}` : 'В работе'}</div>
      <ul className="tasks">
        {shown.map((t) => (
          <TaskRow key={t.key} task={t} now={now} connectorName={connectorName} />
        ))}
      </ul>
    </section>
  )
}
