// Кнопки Mac-приложения: открыть папку данных, config.yaml, журнал в Finder (только при мосте).
import type { BridgeAction } from '../../api/bridge'

const BUTTONS: Array<[BridgeAction, string]> = [
  ['openDataFolder', 'Папка данных'],
  ['openConfig', 'config.yaml'],
  ['revealLog', 'Журнал в Finder'],
]

export default function AppButtons({ onOpen }: { onOpen: (action: BridgeAction) => void }) {
  return (
    <div className="core-buttons">
      {BUTTONS.map(([action, label]) => (
        <button key={action} type="button" className="btn btn-plain" onClick={() => onOpen(action)}>
          {label}
        </button>
      ))}
    </div>
  )
}
