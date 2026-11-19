// Настройки колонки: имя (Enter или потеря фокуса — сохранить) и сведения о ней.
import { useState } from 'react'
import type { Device } from '../../state/model'
import { formatClock } from '../feed/time'

type Props = { device: Device; onRename: (name: string) => void }

/** IP без порта из «IP:port». */
function hostOf(remote: string): string {
  const i = remote.lastIndexOf(':')
  return i > 0 ? remote.slice(0, i) : remote
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
    </div>
  )
}
