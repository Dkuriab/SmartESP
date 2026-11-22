// «Связи»: аккаунты человека в каналах (Telegram и др.). Пишет из связанного аккаунта — ход идёт
// от этого человека: его заметки, таймеры, имя в ленте.
import type { CoreActions } from '../../state/actions'
import type { Person } from '../../state/peopleActions'
import AddLink from './AddLink'
import type { KnownAccount } from './knownAccounts'

const TITLES: Record<string, string> = { telegram: 'Telegram' }

type Props = {
  person: Person
  /** Известные аккаунты (пользователи Telegram-бота). */
  known: KnownAccount[]
  /** Аккаунты, уже связанные с кем-то из людей: «канал/аккаунт». */
  taken: Set<string>
  actions: CoreActions
  onChanged: (person: Person) => void
}

export default function PersonLinks({ person, known, taken, actions, onChanged }: Props) {
  const nameOf = (channel: string, account: string) => known.find((k) => k.channel === channel && k.account === account)?.name
  const apply = (changed: Person | null) => {
    if (changed) onChanged(changed)
    return Boolean(changed)
  }
  const add = async (channel: string, account: string) => apply(await actions.addLink(person.id, channel, account))
  const remove = async (channel: string, account: string) => apply(await actions.removeLink(person.id, channel, account))
  const free = known.filter((k) => !taken.has(`${k.channel}/${k.account}`))
  return (
    <div className="record-panel">
      <div className="cap">Связи</div>
      {person.links.length === 0 && <div className="set-note">Свяжи человека с его Telegram — бот будет отвечать ему как {person.name}.</div>}
      <ul className="recent" aria-label="Связи">
        {person.links.map(({ channel, account }) => (
          <li key={`${channel}/${account}`}>
            <span>{`${TITLES[channel] ?? channel} · ${nameOf(channel, account) ?? ''} id ${account}`}</span>
            <button type="button" className="btn btn-plain" aria-label={`Убрать связь ${channel} ${account}`} onClick={() => void remove(channel, account)}>
              ✕
            </button>
          </li>
        ))}
      </ul>
      <AddLink known={free} onAdd={add} />
    </div>
  )
}
