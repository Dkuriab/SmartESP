// Голос: проигрывание образца и подпись хода скачивания.
import type { Download } from '../../state/model'

/** Проигрывает образец; промис завершается по окончании или ошибке, URL освобождается. */
export function playBlob(blob: Blob): Promise<void> {
  const url = URL.createObjectURL(blob)
  return new Promise((resolve) => {
    const audio = new Audio(url)
    const done = () => {
      URL.revokeObjectURL(url)
      resolve()
    }
    audio.onended = done
    audio.onerror = done
    audio.play().catch(done)
  })
}

/** «25%»; размер неизвестен — скачано в МБ; хода нет — пусто. */
export function progressText(d: Download | undefined): string {
  if (!d) return ''
  if (d.total) return `${Math.floor((d.done / d.total) * 100)}%`
  return `${Math.round(d.done / 1e6)} МБ`
}
