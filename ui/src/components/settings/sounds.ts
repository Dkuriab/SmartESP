// Звуки колонки: названия сигналов, подписи источника и доставки, прослушивание встроенного.
import type { DeviceSound, SoundTone } from '../../state/soundActions'
import { playBlob, stopPlayback } from './voice'

export const TONE_LABELS: Record<SoundTone, string> = {
  wake: 'Слово услышано',
  listen: 'Слушаю (колонка спросила)',
  thinking: 'Думаю',
  attention: 'Внимание (перед объявлением)',
  error: 'Ошибка',
}

/** Порядок сигналов в панели: как они звучат в разговоре. */
export const TONE_ORDER: SoundTone[] = ['wake', 'listen', 'thinking', 'attention', 'error']

const DELIVERY: Record<DeviceSound['delivery'], string> = {
  ok: '',
  pending: 'ждёт отправки',
  sending: 'отправляется…',
  failed: 'не доставлен',
  unsupported: '',
  offline: 'колонка получит его при подключении',
}

/** Откуда звук: встроенный, общий для всех или свой этой колонки (с именем файла). */
export function sourceText(sound: DeviceSound): string {
  if (sound.source === 'builtin' || !sound.sound) return 'встроенный'
  const name = `${sound.sound.name} · ${sound.sound.duration_s.toFixed(1)} с`
  return sound.source === 'all' ? `общий: ${name}` : `только здесь: ${name}`
}

/** Состояние доставки на колонку; всё на месте — пусто. */
export function deliveryText(sound: DeviceSound): string {
  const text = DELIVERY[sound.delivery]
  return sound.delivery === 'failed' && sound.error ? `${text}: ${sound.error}` : text
}

/** Встроенный звук: WAV из tools/make_sounds.py лежит в сборке интерфейса (ui/public/sounds). */
export function playBuiltin(tone: SoundTone): void {
  stopPlayback()
  void new Audio(`${import.meta.env.BASE_URL}sounds/${tone}.wav`).play().catch(() => {})
}

/** Свой звук (WAV от ядра). */
export function playSound(blob: Blob): void {
  void playBlob(blob)
}
