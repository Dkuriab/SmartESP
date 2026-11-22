// Образцы голоса человека: когда, с какой колонки, длительность, громкость; удалить неудачный.
// Звук образцов ядро не хранит — только голосовые отпечатки.
import type { CoreActions } from '../../state/actions'
import type { Device } from '../../state/model'
import type { Person } from '../../state/peopleActions'
import { formatTime } from '../feed/time'

type Props = { person: Person; devices: Device[]; actions: CoreActions; onChanged: () => void }

export function deviceName(devices: Device[], id: string): string {
  return devices.find((d) => d.device_id === id)?.name || id
}

export default function SampleList({ person, devices, actions, onChanged }: Props) {
  if (person.samples.length === 0) return null
  const remove = async (id: string) => {
    if (await actions.deleteSample(person.id, id)) onChanged()
  }
  return (
    <ul className="recent" aria-label="Образцы голоса">
      {[...person.samples].reverse().map((s) => (
        <li key={s.id}>
          <span>{`${formatTime(s.at)} · ${deviceName(devices, s.device_id)} · ${s.seconds.toFixed(1)} с · ${Math.round(s.peak_db)} дБ`}</span>
          <button type="button" className="btn btn-plain" aria-label={`Удалить образец ${formatTime(s.at)}`} onClick={() => void remove(s.id)}>
            ✕
          </button>
        </li>
      ))}
    </ul>
  )
}
