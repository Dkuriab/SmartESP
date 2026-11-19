// Время работы ядра по-русски: «3 ч 05 мин», «12 мин», «40 с».

export function formatUptime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  const days = Math.floor(s / 86400)
  const hours = Math.floor((s % 86400) / 3600)
  const minutes = Math.floor((s % 3600) / 60)
  if (days > 0) return `${days} д ${hours} ч`
  if (hours > 0) return `${hours} ч ${String(minutes).padStart(2, '0')} мин`
  if (minutes > 0) return `${minutes} мин`
  return `${s} с`
}
