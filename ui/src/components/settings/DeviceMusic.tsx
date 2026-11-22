// Музыка на колонке: что играет и кнопки пауза/продолжить, дальше, стоп. Колонке нужен протокол ≥ 5.
import type { Device, Stream, StreamAction } from '../../state/model'

/** С этой версии протокола колонка играет поток звука с ядра (прошивка 0.6.0). */
export const MIN_STREAM_PROTOCOL = 5

type Props = { device: Device; stream?: Stream; onControl: (action: StreamAction) => void }

function stateText(stream?: Stream): string {
  if (!stream || stream.state === 'idle') return stream?.error || 'Не играет'
  const place = stream.count > 1 ? ` (${stream.index + 1} из ${stream.count})` : ''
  const what = `«${stream.title}»${place}`
  return stream.state === 'playing' ? `Играет ${what}` : `Пауза: ${what}`
}

export default function DeviceMusic({ device, stream, onControl }: Props) {
  if (device.connected && device.protocol < MIN_STREAM_PROTOCOL && !stream) {
    return (
      <div className="field-block device-music">
        <span className="lbl">Музыка</span>
        <div className="set-note">Музыку играют колонки с прошивкой 0.6.0</div>
      </div>
    )
  }
  const active = stream !== undefined && stream.state !== 'idle'
  const playing = stream?.state === 'playing'
  return (
    <div className="field-block device-music">
      <span className="lbl">Музыка</span>
      <div className="device-music-state cut" role="status" aria-label="Музыка">
        {stateText(stream)}
      </div>
      {active && (
        <div className="device-file-row">
          <button type="button" className="btn small" onClick={() => onControl(playing ? 'pause' : 'resume')}>
            {playing ? 'Пауза' : 'Продолжить'}
          </button>
          {stream.count > 1 && (
            <button type="button" className="btn small" onClick={() => onControl('next')}>
              Дальше
            </button>
          )}
          <button type="button" className="btn small" onClick={() => onControl('stop')}>
            Стоп
          </button>
        </div>
      )}
    </div>
  )
}
