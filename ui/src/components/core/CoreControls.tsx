// Перезапуск и остановка ядра; остановка — с подтверждением на месте (в окне приложения нет confirm).
import { useCallback, useRef, useState } from 'react'

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

type ConfirmProps = { sending: boolean; onYes: () => void; onCancel: () => void }

/** Подтверждение остановки; фокус сразу на безопасной «Отмена». */
function StopConfirm({ sending, onYes, onCancel }: ConfirmProps) {
  const focusOnMount = useCallback((el: HTMLButtonElement | null) => el?.focus(), [])
  return (
    <div className="remove-ask" role="alertdialog" aria-label="Остановить ядро?">
      <p className="core-note">Остановить ядро? Ассистент перестанет отвечать, само ядро не перезапустится.</p>
      <button type="button" className="btn btn-danger" disabled={sending} onClick={onYes}>
        Да, остановить
      </button>
      <button type="button" className="btn btn-plain" ref={focusOnMount} onClick={onCancel}>
        Отмена
      </button>
    </div>
  )
}

export default function CoreControls({ online, busy, onRestart, onStop, inApp }: Props) {
  const [phase, setPhase] = useState<Phase>('idle')
  const refocus = useRef(false) // «Отмена» — фокус обратно на «Остановить», а не на <body>
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
    const cancel = () => {
      refocus.current = true
      setPhase('idle')
    }
    return <StopConfirm sending={phase === 'sending' || busy} onYes={() => void stop()} onCancel={cancel} />
  }
  const stopRef = (el: HTMLButtonElement | null) => {
    if (el && refocus.current) {
      refocus.current = false
      el.focus()
    }
  }
  return (
    <div className="core-buttons">
      <button type="button" className="btn" disabled={!online || busy} onClick={onRestart}>
        Перезапустить
      </button>
      <button type="button" className="btn btn-danger" ref={stopRef} disabled={!online || busy} onClick={() => setPhase('confirm')}>
        Остановить
      </button>
    </div>
  )
}
