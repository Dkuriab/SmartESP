// Настройки колонки: имя (Enter или потеря фокуса — сохранить), сведения, файл, обновление и звуки.
import { useState } from 'react'
import type { Device, FilePhase, Stream, StreamAction } from '../../state/model'
import type { SoundActions } from '../../state/soundActions'
import { formatClock } from '../feed/time'
import DeviceEcho from './DeviceEcho'
import DeviceFile, { MIN_SPEECH_PROTOCOL } from './DeviceFile'
import DeviceMusic from './DeviceMusic'
import DeviceSounds from './DeviceSounds'
import DeviceUpdate from './DeviceUpdate'
import DeviceVolume from './DeviceVolume'

type Props = {
  device: Device
  onRename: (name: string) => void
  /** Фаза файла на колонке; нет — не играет. */
  filePhase?: FilePhase
  onPlayFile: (file: File) => void
  onStopFile: () => void
  /** Прошивка (.bin) на колонку по воздуху. */
  onInstallFirmware: (file: File) => void
  /** Громкость колонки, % (в настройки ядра). */
  onVolume: (volume: number) => void
  /** Свои звуки сигналов: tick растёт с событиями sounds. */
  sounds: { tick: number; actions: SoundActions }
  /** Музыка на колонке (нет — не играет) и управление ею. */
  stream?: Stream
  onStream: (action: StreamAction) => void
  /** Громкость музыки на колонке, %. */
  onStreamVolume: (percent: number) => void
  /** Калибровка эха (прошивка 0.7.0). */
  onCalibrateEcho: () => void
}

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

export default function DeviceSettings(props: Props) {
  const { device, onRename, filePhase, onPlayFile, onStopFile, onInstallFirmware, onVolume, sounds, stream, onStream } = props
  const { onCalibrateEcho, onStreamVolume } = props
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
      <DeviceVolume key={device.volume} volume={device.volume} disabled={false} onSave={onVolume} />
      {info.map(([label, value]) => (
        <div key={label} className="field">
          <span className="lbl">{label}</span>
          <span className="val-text">{value}</span>
        </div>
      ))}
      {device.connected && device.protocol < MIN_SPEECH_PROTOCOL && (
        <div className="set-note">Обновите прошивку, чтобы ассистент мог говорить сам</div>
      )}
      <DeviceMusic device={device} stream={stream} onControl={onStream} onVolume={onStreamVolume} />
      <DeviceFile device={device} phase={filePhase} onPlay={onPlayFile} onStop={onStopFile} />
      <DeviceUpdate device={device} onInstall={onInstallFirmware} />
      <DeviceEcho device={device} onCalibrate={onCalibrateEcho} />
      <DeviceSounds device={device} tick={sounds.tick} actions={sounds.actions} />
    </div>
  )
}
