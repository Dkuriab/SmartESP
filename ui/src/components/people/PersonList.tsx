// Список людей (сколько образцов голоса у каждого) и добавление человека по имени.
import { useState } from 'react'
import type { Person } from '../../state/peopleActions'

type Props = {
  people: Person[] | null
  selectedId: string
  onSelect: (id: string) => void
  /** Добавляет человека; true — добавлен (поле очищается). */
  onAdd: (name: string) => Promise<boolean>
}

export default function PersonList({ people, selectedId, onSelect, onAdd }: Props) {
  const [name, setName] = useState('')
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (name.trim() && (await onAdd(name.trim()))) setName('')
  }
  return (
    <nav className="people-side" aria-label="Люди">
      <div className="cap">Люди дома</div>
      {(people ?? []).map((p) => (
        <button key={p.id} type="button" className={`people-item${p.id === selectedId ? ' on' : ''}`} onClick={() => onSelect(p.id)}>
          <span className="cut">{p.name}</span>
          <span className="people-count">{p.samples.length}</span>
        </button>
      ))}
      <form className="people-add" onSubmit={(e) => void submit(e)}>
        <input className="val" value={name} maxLength={40} placeholder="Имя" aria-label="Имя нового человека" onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="btn" disabled={!name.trim()}>
          Добавить
        </button>
      </form>
      <p className="set-note">Голос не пароль: узнавание делает ответы, заметки и таймеры личными, но ничего не открывает.</p>
    </nav>
  )
}
