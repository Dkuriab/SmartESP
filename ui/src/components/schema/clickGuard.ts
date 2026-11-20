// Клик после перетаскивания: браузер шлёт click при отпускании мыши над тем же узлом,
// и узел выбрался бы (открылись бы его настройки). Такой клик гасим.

/** Сколько после конца перетаскивания клик по узлу не считается выбором, мс. */
export const CLICK_AFTER_DRAG_MS = 300

/** Сторож клика; now — часы (подменяются в тестах). */
export function createClickGuard(now: () => number = () => performance.now()) {
  let droppedAt = -Infinity
  return {
    /** Перетаскивание узла закончилось. */
    dragged: () => {
      droppedAt = now()
    },
    /** Считать ли клик выбором узла. */
    allowsClick: () => now() - droppedAt >= CLICK_AFTER_DRAG_MS,
  }
}
