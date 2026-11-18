// Время хода для интерфейса.

/** Unix-время в секундах -> HH:MM:SS по местному времени. */
export function formatTime(at: number): string {
  const d = new Date(at * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}
