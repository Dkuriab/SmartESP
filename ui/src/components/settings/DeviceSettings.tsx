// Настройки колонки: имя (Enter или потеря фокуса — сохранить) и сведения о ней.
import { useState } from 'react'
import type { Device } from '../../state/model'
import { formatClock } from '../feed/time'

/** С этой версии протокола колонка принимает речь, начатую ядром. */
const MIN_SPEECH_PROTOCOL = 3

type Props = { device: Device; onRename: (name: string) => void }

/** Адрес без порта: «IP:port» и «[IPv6]:port»; голый IPv6 (много «:») — как есть. */
function hostOf(remote: string): string {
  const bracketed = /^\[([^\]]+)\](?::\d+)?$/.exec(remote)
  if (bracketed) return bracketed[1] ?? remote
  const parts = remote.split(':')
  return parts.length === 2 ? (parts[0] ?? remote) : remote
}

function presence(d: Device): string {
  if (d.connected) return 'в сети'
  return d.last_seen ? `была в ${formatClock(d.last_seen)}` : 'не подключалась'
}

export default function DeviceSettings({ device, onRename }: Props) {
  const [draft, setDraft] = useState(device.name)
  const save = () => {
    const name = draft.trim()
    // пустое имя не шлём: колонка осталась бы подписанной MAC без явного намерения
    if (name && name !== device.name) onRename(name)
    else setDraft(device.name)
  }
  const info: Array<[string, string]> = [
    ['MAC', device.device_id],
    ['IP', hostOf(device.remote) || '—'],
    ['Прошивка', device.fw || '—'],
    ['Связь', presence(device)],
  ]
  return (
    <div className="set">
      <h3 className="set-title cut">🔊 {device.name || device.device_id}</h3>
      <div className="set-sub">Колонка</div>
      <label className="field">
        <span className="lbl">Имя</span>
        <input
          className="val"
          value={draft}
          placeholder={device.device_id}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
          onBlur={save}
        />
      </label>
      {info.map(([label, value]) => (
        <div key={label} className="field">
          <span className="lbl">{label}</span>
          <span className="val-text">{value}</span>
        </div>
      ))}
      {device.connected && device.protocol < MIN_SPEECH_PROTOCOL && (
        <div className="set-note">Обновите прошивку, чтобы Кузя мог говорить сам</div>
      )}
    </div>
  )
}
