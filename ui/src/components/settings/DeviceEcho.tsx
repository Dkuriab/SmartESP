// Калибровка эха колонки (прошивка 0.7.0): сдвиг образца, кнопка, итог и две проверки после неё.
import type { Device } from '../../state/model'

type Props = { device: Device; onCalibrate: () => void }

const ERRORS: Record<string, string> = {
  busy: 'колонка была занята',
  quiet: 'динамик не сыграл шум — проверьте громкость',
  weak: 'микрофон не услышал шум уверенно — громче, тише в комнате',
}

/** Строка итога по состоянию калибровки. */
export function echoText(echo: NonNullable<Device['echo']>): string {
  const sure = `уверенность ${Math.round(echo.confidence * 100)}%`
  switch (echo.state) {
    case 'sent':
    case 'running':
      return 'Калибровка: колонка играет шум, не говорите…'
    case 'done':
      return `Готово: сдвиг ${echo.delay_ms} мс (был ${echo.previous_ms}), ${sure}`
    case 'failed':
      return `Не вышло: ${ERRORS[echo.error] ?? (echo.error || 'ошибка')}. Сдвиг прежний — ${echo.delay_ms} мс`
    default:
      return `Сдвиг образца: ${echo.delay_ms} мс`
  }
}

export default function DeviceEcho({ device, onCalibrate }: Props) {
  const echo = device.echo
  if (!device.connected || !echo) return null // прошивка до 0.7.0 сдвиг не сообщает
  const running = echo.state === 'sent' || echo.state === 'running'
  return (
    <div className="field-block device-echo">
      <span className="lbl">Эхоподавление</span>
      <div className="device-music-state" role="status" aria-label="Эхо">
        {echoText(echo)}
      </div>
      <button type="button" className="btn small" disabled={running} onClick={onCalibrate}>
        Калибровка эха
      </button>
      <div className="set-note">
        Колонка 1,5 с играет шум и по микрофону находит, на сколько задержать звук динамика для
        эхоподавления. В комнате — тихо. После калибровки проверьте сами: 1) громкая музыка на колонке
        и слово пробуждения с 2–3 м — колонка его слышит; 2) длинный ответ на полной громкости не будит колонку
        сам.
      </div>
    </div>
  )
}
