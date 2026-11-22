// Итоги прогонов: когда, какая цель, сколько узнала и сколько ложных; лучший — ★; «Встроить» в прошивку.
import type { TrainRun } from '../../state/trainingActions'
import { bestRuns, decimal, ofTotal, percent, runDate } from './runs'

type Props = { runs: TrainRun[]; busy: boolean; onEmbed: (run: string) => void }

export default function RunsTable({ runs, busy, onEmbed }: Props) {
  if (runs.length === 0) return <div className="set-note">Прогонов ещё нет — обучите цель.</div>
  const best = bestRuns(runs)
  return (
    <table className="phrase-table runs-table">
      <thead>
        <tr>
          <th>Когда</th>
          <th>Цель</th>
          <th title="Отложенные живые записи, которых модель не видела">Твой голос</th>
          <th title="Проверочные клипы">Узнаёт</th>
          <th title="Ложных срабатываний в час на записи застолья">Ложных/ч</th>
          <th title="Записи «Не откликаться на», принятые за слово">Похожие</th>
          <th>Порог</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {runs.map((r) => {
          const name = String(r.run)
          return (
            <tr key={name} className={best.has(name) ? 'best' : ''}>
              <td>{`${best.has(name) ? '★ ' : ''}${runDate(name)}`}</td>
              <td>{String(r.title ?? r.target ?? '')}</td>
              <td>{ofTotal(r.real_heard, 'detected')}</td>
              <td>{percent(r.recall)}</td>
              <td>{decimal(r.false_per_hour)}</td>
              <td>{ofTotal(r.real_negative, 'false_wakes')}</td>
              <td>{decimal(r.cutoff)}</td>
              <td>
                <button type="button" className="btn btn-plain" disabled={busy} onClick={() => onEmbed(name)}>
                  Встроить
                </button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
