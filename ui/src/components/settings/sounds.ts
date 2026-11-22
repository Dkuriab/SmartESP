// Звуки колонки: названия сигналов, подписи звука и доставки, прослушивание встроенного.
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
  ok: 'на колонке',
  pending: 'доставляется',
  sending: 'доставляется',
  failed: 'ошибка',
  unsupported: 'колонка не умеет свои звуки',
  offline: 'ждёт подключения колонки',
}

/** Какой звук задан: встроенный или свой файл (имя и длина). */
export function soundText(sound: DeviceSound): string {
  return sound.sound ? `${sound.sound.name} · ${sound.sound.duration_s.toFixed(1)} с` : 'встроенный'
}

/** Состояние доставки на колонку; у ошибки — причина. */
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
