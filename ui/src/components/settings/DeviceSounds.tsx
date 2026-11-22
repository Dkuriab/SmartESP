// Звуки колонки: пять сигналов этой колонки. Колонка не в сети — правки ждут её подключения;
// «Скопировать на другие колонки» отдаёт этот набор всем другим известным колонкам.
import { useEffect, useState } from 'react'
import type { Device } from '../../state/model'
import type { DeviceSound, SoundActions, SoundsOverview } from '../../state/soundActions'
import SoundRow from './SoundRow'
import { TONE_ORDER, playBuiltin, playSound } from './sounds'

type Props = {
  device: Device
  /** Растёт с событиями sounds — обзор перечитывается. */
  tick: number
  actions: SoundActions
}

/** Обзор звуков; перечитывается при смене tick и после своих изменений (reload). */
function useOverview(actions: SoundActions, tick: number): [SoundsOverview | null, () => void] {
  const [overview, setOverview] = useState<SoundsOverview | null>(null)
  const [own, setOwn] = useState(0)
  const { loadSounds } = actions
  useEffect(() => {
    let alive = true
    void loadSounds().then((data) => alive && setOverview(data))
    return () => {
      alive = false
    }
  }, [loadSounds, tick, own])
  return [overview, () => setOwn((n) => n + 1)]
}

export default function DeviceSounds({ device, tick, actions }: Props) {
  const [overview, reload] = useOverview(actions, tick)
  const [busy, setBusy] = useState(false)
  const id = device.device_id
  const info = overview?.devices.find((d) => d.device_id === id)
  if (!info) return null
  const run = async (work: Promise<unknown>) => {
    setBusy(true)
    await work
    setBusy(false)
    reload()
  }
  const play = async (sound: DeviceSound) => {
    if (!sound.sound) return playBuiltin(sound.tone)
    const blob = await actions.fetchSound(sound.sound.sha256)
    if (blob) playSound(blob)
  }
  const tones = TONE_ORDER.map((tone) => info.tones.find((t) => t.tone === tone)).filter((t) => t !== undefined)
  const others = (overview?.devices.length ?? 1) > 1
  return (
    <div className="field field-block">
      <span className="cap set-label">Звуки</span>
      {info.supported === false && <div className="set-note">Свои звуки — с прошивки 0.6.0: обновите колонку</div>}
      <ul className="sound-list">
        {tones.map((sound) => (
          <SoundRow key={sound.tone} sound={sound} locked={busy}
            onPlay={() => void play(sound)}
            onReplace={(file) => void run(actions.uploadSound(sound.tone, file, id))}
            onReset={() => void run(actions.resetSound(sound.tone, id))}
            onRetry={() => void actions.resyncSounds(id)} />
        ))}
      </ul>
      <button type="button" className="btn small" disabled={busy || !others} onClick={() => void run(actions.copySounds(id))}>
        Скопировать на другие колонки
      </button>
      <div className="set-note">Короткий звук (MP3, WAV, OGG, M4A, FLAC) — до 3 с; тишина по краям обрезается, громкость выравнивается.</div>
    </div>
  )
}
