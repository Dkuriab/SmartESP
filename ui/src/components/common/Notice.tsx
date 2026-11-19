// Уведомление: короткий текст, закрывается крестиком; «ok» закрывается само.
import { useEffect, useEffectEvent } from 'react'
import type { Notice as NoticeData } from '../../state/model'
import './common.css'

type Props = { notice: NoticeData; onDismiss: () => void }

/** Через сколько закрывается уведомление «ok». */
const OK_MS = 4000

export default function Notice({ notice, onDismiss }: Props) {
  const dismiss = useEffectEvent(onDismiss)
  // новое уведомление (новый объект) — отсчёт заново; ошибки висят, пока их не закроют
  useEffect(() => {
    if (notice.tone !== 'ok') return
    const timer = setTimeout(() => dismiss(), OK_MS)
    return () => clearTimeout(timer)
  }, [notice])
  return (
    <div className={`notice notice-${notice.tone}`} role={notice.tone === 'error' ? 'alert' : 'status'}>
      <span className="notice-text">{notice.text}</span>
      <button type="button" className="icon-btn" aria-label="Закрыть" onClick={onDismiss}>
        ×
      </button>
    </div>
  )
}
