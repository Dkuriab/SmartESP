// Новая связь человека: известный пользователь Telegram-бота из списка или канал и аккаунт вручную.
import { useState } from 'react'
import type { KnownAccount } from './knownAccounts'
import { TELEGRAM } from './knownAccounts'

const MANUAL = 'manual'

type Props = {
  /** Известные аккаунты, ещё ни с кем не связанные. */
  known: KnownAccount[]
  onAdd: (channel: string, account: string) => Promise<boolean>
}

export default function AddLink({ known, onAdd }: Props) {
  const [pick, setPick] = useState('')
  const [channel, setChannel] = useState(TELEGRAM)
  const [account, setAccount] = useState('')
  const choice = pick || (known.length > 0 ? '0' : MANUAL)
  const chosen = choice === MANUAL ? null : known[Number(choice)]
  const link = chosen ?? { channel: channel.trim(), account: account.trim() }
  const add = async () => {
    if (!(await onAdd(link.channel, link.account))) return
    setAccount('')
    setPick('')
  }
  return (
    <div className="people-link-add">
      <select className="val" aria-label="Кого связать" value={choice} onChange={(e) => setPick(e.target.value)}>
        {known.map((k, i) => (
          <option key={`${k.channel}/${k.account}`} value={String(i)}>{`Telegram: ${k.name || k.account} (id ${k.account})`}</option>
        ))}
        <option value={MANUAL}>Другой аккаунт…</option>
      </select>
      {chosen === null && (
        <>
          <input className="val" aria-label="Канал" value={channel} maxLength={32} onChange={(e) => setChannel(e.target.value)} />
          <input className="val" aria-label="Аккаунт" placeholder="id в канале" value={account} maxLength={64} onChange={(e) => setAccount(e.target.value)} />
        </>
      )}
      <button type="button" className="btn" disabled={!link.channel || !link.account} onClick={() => void add()}>
        Связать
      </button>
    </div>
  )
}
