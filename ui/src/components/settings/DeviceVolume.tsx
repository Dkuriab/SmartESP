// Громкость колонки: ползунок, сохраняется, когда отпустили (ядро сразу шлёт её колонке).
import { useState } from 'react'

type Props = { volume: number; disabled: boolean; onSave: (volume: number) => void }

export default function DeviceVolume({ volume, disabled, onSave }: Props) {
  const [draft, setDraft] = useState(volume)
  const save = () => {
    if (draft !== volume) onSave(draft)
  }
  return (
    <label className="field">
      <span className="lbl">Громкость</span>
      <input
        type="range"
        className="val"
        min={0}
        max={100}
        step={5}
        value={draft}
        disabled={disabled}
        aria-label="Громкость"
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={save}
        onKeyUp={save}
        onBlur={save}
      />
      <span className="val-text">{`${draft} %`}</span>
    </label>
  )
}
