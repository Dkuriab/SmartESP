// Последние узнавания: когда, где, кто (или «не узнан») и сходство — по ним видно, подходит ли порог.
import type { Device } from '../../state/model'
import type { Recognition } from '../../state/peopleActions'
import { formatTime } from '../feed/time'
import { deviceName } from './SampleList'

type Props = { items: Recognition[]; devices: Device[] }

export default function Recognitions({ items, devices }: Props) {
  return (
    <div className="record-panel">
      <div className="cap">Последние узнавания</div>
      {items.length === 0 ? (
        <div className="set-note">Пока никого: узнавание идёт на каждой фразе, когда записан хотя бы один голос.</div>
      ) : (
        <table className="phrase-table people-table">
          <thead>
            <tr>
              <th>Время</th>
              <th>Колонка</th>
              <th>Кто</th>
              <th>Сходство</th>
            </tr>
          </thead>
          <tbody>
            {items.map((r) => (
              <tr key={`${r.at}/${r.turn}`}>
                <td>{formatTime(r.at)}</td>
                <td>{deviceName(devices, r.device_id)}</td>
                <td className={r.person_id ? 'done' : 'people-unknown'}>{r.name || 'не узнан'}</td>
                <td>{`${r.score.toFixed(2)} · ${Math.round(r.ms)} мс`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
