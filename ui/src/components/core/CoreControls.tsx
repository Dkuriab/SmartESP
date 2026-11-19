// Перезапуск и остановка ядра; остановка — с подтверждением на месте (в окне приложения нет confirm).
import { useState } from 'react'

type Props = {
  online: boolean
  /** Ядро перезапускается или останавливается: новые просьбы не шлём. */
  busy: boolean
  onRestart: () => void
  /** true — ядро приняло просьбу остановиться. */
  onStop: () => Promise<boolean>
  /** Открыто в Mac-приложении: запустить снова можно оттуда. */
  inApp: boolean
}

type Phase = 'idle' | 'confirm' | 'sending' | 'stopped'

export default function CoreControls({ online, busy, onRestart, onStop, inApp }: Props) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [wasOnline, setWasOnline] = useState(online)
  if (online !== wasOnline) {
    // связь вернулась — ядро снова запущено: кнопки снова нужны
    setWasOnline(online)
    if (online) setPhase('idle')
  }
  const stop = async () => {
    setPhase('sending')
    setPhase((await onStop()) ? 'stopped' : 'idle')
  }
  if (phase === 'stopped') {
    const again = inApp ? 'Запустить снова — кнопкой в окне приложения.' : 'Запустить снова — из терминала или приложения.'
    return <p className="core-note" role="status">Ядро останавливается. {again}</p>
  }
  if (phase !== 'idle') {
    return (
      <div className="remove-ask">
        <p className="core-note">Остановить ядро? Кузя перестанет отвечать, само ядро не перезапустится.</p>
        <button type="button" className="btn btn-danger" disabled={phase === 'sending' || busy} onClick={() => void stop()}>
          Да, остановить
        </button>
        <button type="button" className="btn btn-plain" onClick={() => setPhase('idle')}>
          Отмена
        </button>
      </div>
    )
  }
  return (
    <div className="core-buttons">
      <button type="button" className="btn" disabled={!online || busy} onClick={onRestart}>
        Перезапустить
      </button>
      <button type="button" className="btn btn-danger" disabled={!online || busy} onClick={() => setPhase('confirm')}>
        Остановить
      </button>
    </div>
  )
}
