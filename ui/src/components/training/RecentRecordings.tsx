// Последние записи фразы человека: прослушать и удалить неудачную.
import { useEffect, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { PhraseRecording } from '../../state/trainingActions'

const SHOWN = 5

type Props = { kit: string; phrase: string; person: string; actions: CoreActions; onDeleted: () => void }

export default function RecentRecordings({ kit, phrase, person, actions, onDeleted }: Props) {
  const [items, setItems] = useState<PhraseRecording[]>([])
  const { listRecordings } = actions
  useEffect(() => {
    let alive = true
    void listRecordings(kit, phrase, person).then((list) => alive && setItems(list))
    return () => {
      alive = false
    }
  }, [listRecordings, kit, phrase, person])
  const play = async (name: string) => {
    const blob = await actions.fetchRecording(kit, phrase, person, name)
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => URL.revokeObjectURL(url)
    void audio.play()
  }
  const remove = async (name: string) => {
    if (!(await actions.deleteRecording(kit, phrase, person, name))) return
    setItems((list) => list.filter((r) => r.name !== name))
    onDeleted()
  }
  if (items.length === 0) return null
  return (
    <ul className="recent" aria-label="Последние записи">
      {items.slice(-SHOWN).reverse().map((r) => (
        <li key={r.name}>
          <span>{`${r.name} · ${r.seconds.toFixed(1)} с · ${Math.round(r.peak_db)} дБ`}</span>
          <button type="button" className="btn btn-plain" aria-label={`Прослушать ${r.name}`} onClick={() => void play(r.name)}>▶</button>
          <button type="button" className="btn btn-plain" aria-label={`Удалить ${r.name}`} onClick={() => void remove(r.name)}>✕</button>
        </li>
      ))}
    </ul>
  )
}
