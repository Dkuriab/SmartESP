// Запись с колонки: колонка, чей голос, фраза; «Записать» — колонка пикает и слушает до паузы.
// «Подряд» записывает раз за разом, пока не нажмёшь «Стоп» (или три неудачи подряд).
import { useRef, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import type { PhraseRecording, TrainKit } from '../../state/trainingActions'
import RecentRecordings from './RecentRecordings'

const PERSON_KEY = 'smartesp.training.person'
const PAUSE_MS = 1200 // между записями «подряд»: успеть отойти или сменить голос

function savedPerson(): string {
  try {
    return localStorage.getItem(PERSON_KEY) ?? ''
  } catch {
    return ''
  }
}

function rememberPerson(name: string) {
  try {
    localStorage.setItem(PERSON_KEY, name)
  } catch {
    // без хранилища имя просто не запомнится
  }
}

/** Что сказать о готовой записи: громкость и длительность. */
export function describeRecording(r: PhraseRecording): { text: string; warn: boolean } {
  const base = `Записано ${r.name} · ${r.seconds.toFixed(1)} с · ${Math.round(r.peak_db)} дБ`
  if (r.peak_db < -35) return { text: `${base} — тихо: подойди ближе или говори громче`, warn: true }
  if (r.seconds > 3) return { text: `${base} — длинная: могли попасть посторонние звуки`, warn: true }
  return { text: base, warn: false }
}

type Request = { kit: TrainKit; device: string; person: string; phrase: string }

/** Запись по одной или «подряд»: состояние кнопки, подсказка и номер версии (для списка записей). */
function useRecorder(actions: CoreActions, onRecorded: () => void, hint: string) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState({ text: hint, warn: false })
  const [version, setVersion] = useState(0)
  const stop = useRef(false)
  const once = async ({ kit, device, person, phrase }: Request): Promise<boolean> => {
    setNote({ text: `Скажи «${phrase}» после сигнала`, warn: false })
    const out = await actions.recordPhrase({ kit: kit.id, deviceId: device, phrase, person })
    if (!out.ok) setNote({ text: out.text, warn: true })
    else {
      setNote(describeRecording(out.recording))
      setVersion((v) => v + 1)
      onRecorded()
    }
    return out.ok
  }
  const start = async (request: Request, series: boolean) => {
    stop.current = false
    setBusy(true)
    rememberPerson(request.person)
    for (let fails = 0; fails < 3 && !stop.current; ) {
      fails = (await once(request)) ? 0 : fails + 1
      if (!series) break
      await new Promise((resolve) => setTimeout(resolve, PAUSE_MS))
    }
    setBusy(false)
  }
  return { busy, note, version, start, stop: () => (stop.current = true) }
}

type Props = { kit: TrainKit; phrase: string; onPhrase: (phrase: string) => void; state: CoreState; actions: CoreActions; onRecorded: () => void }

export default function RecordPanel({ kit, phrase, onPhrase, state, actions, onRecorded }: Props) {
  const speakers = (state.status?.devices ?? []).filter((d) => d.connected && (d.protocol ?? 0) >= 3)
  const [deviceId, setDeviceId] = useState('')
  const [person, setPerson] = useState(savedPerson)
  const [series, setSeries] = useState(false)
  const rec = useRecorder(actions, onRecorded, kit.record_hint)
  const device = speakers.some((d) => d.device_id === deviceId) ? deviceId : (speakers[0]?.device_id ?? '')
  const who = person.trim()
  const ready = Boolean(device && who && phrase) && !rec.busy
  return (
    <div className="record-panel">
      <div className="cap">Записать с колонки</div>
      <label className="field">
        <span className="lbl">Колонка</span>
        <select className="val" value={device} disabled={rec.busy} onChange={(e) => setDeviceId(e.target.value)}>
          {speakers.length === 0 && <option value="">нет колонки с прошивкой 0.4+</option>}
          {speakers.map((d) => <option key={d.device_id} value={d.device_id}>{d.name || d.device_id}</option>)}
        </select>
      </label>
      <label className="field">
        <span className="lbl">Чей голос</span>
        <input className="val" value={person} maxLength={40} placeholder="Имя" disabled={rec.busy} onChange={(e) => setPerson(e.target.value)} />
      </label>
      <label className="field">
        <span className="lbl">Фраза</span>
        <select className="val" value={phrase} disabled={rec.busy} onChange={(e) => onPhrase(e.target.value)}>
          {kit.phrases.map((p) => <option key={p.phrase} value={p.phrase}>{p.phrase}</option>)}
        </select>
      </label>
      <label className="link-head">
        <input type="checkbox" className="switch" checked={series} disabled={rec.busy} onChange={(e) => setSeries(e.target.checked)} />
        <span className="link-name">Подряд, пока не нажму «Стоп»</span>
      </label>
      <div className="record-buttons">
        <button type="button" className="btn" disabled={!ready} onClick={() => void rec.start({ kit, device, person: who, phrase }, series)}>{rec.busy ? 'Слушаю…' : 'Записать'}</button>
        {rec.busy && series && <button type="button" className="btn btn-plain" onClick={rec.stop}>Стоп</button>}
      </div>
      <div className={rec.note.warn ? 'set-note warn' : 'set-note'} role="status">{rec.note.text}</div>
      {who && phrase && <RecentRecordings key={`${phrase}/${who}/${rec.version}`} kit={kit.id} phrase={phrase} person={who} actions={actions} onDeleted={onRecorded} />}
    </div>
  )
}
