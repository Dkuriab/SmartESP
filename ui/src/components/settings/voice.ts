// Голос: проигрывание образца и подпись хода скачивания.
import type { Download } from '../../state/model'

/** Звучащий сейчас образец: одновременно играет только один. */
let current: { audio: HTMLAudioElement; finish: () => void } | null = null

/** Останавливает звучащий образец (его промис из playBlob завершается). */
export function stopPlayback(): void {
  current?.finish()
}

/**
 * Проигрывает образец, остановив прежний; промис завершается по окончании,
 * ошибке или остановке, URL освобождается. Браузер отказался играть
 * (play() отклонён) — вызывается onRefused.
 */
export function playBlob(blob: Blob, onRefused: () => void = () => {}): Promise<void> {
  stopPlayback()
  const url = URL.createObjectURL(blob)
  return new Promise((resolve) => {
    const audio = new Audio(url)
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      if (current?.audio === audio) current = null
      audio.pause()
      URL.revokeObjectURL(url)
      resolve()
    }
    current = { audio, finish }
    audio.onended = finish
    audio.onerror = finish
    audio.play().catch(() => {
      if (!finished) onRefused() // остановленный раньше образец — не ошибка
      finish()
    })
  })
}

/** «25%»; размер неизвестен — скачано в МБ; хода нет — пусто. */
export function progressText(d: Download | undefined): string {
  if (!d) return ''
  if (d.total) return `${Math.floor((d.done / d.total) * 100)}%`
  return `${Math.round(d.done / 1e6)} МБ`
}
