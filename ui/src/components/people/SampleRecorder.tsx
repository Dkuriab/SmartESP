// Запись образцов голоса с колонки: колонка, подсказка фразы, «Записать» по одной или «подряд».
import { useRef, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import type { Person, VoiceSample } from '../../state/peopleActions'

/** Сколько образцов советуем: меньше — узнавание неуверенное, больше 10 — почти не помогает. */
export const ENOUGH = 5
const MAX_SERIES = 10 // «подряд» останавливается само, когда образцов столько
const PAUSE_MS = 1200 // между записями «подряд»
// фразы-подсказки: обычная речь 2–4 с, разные звуки; говорить можно и своё
export const PROMPTS = [
  'Кузя, какая сегодня погода?',
  'Поставь таймер на десять минут.',
  'Запиши в заметки купить молоко и хлеб.',
  'Напомни мне завтра позвонить бабушке.',
  'Расскажи что-нибудь интересное про космос.',
  'Сколько градусов будет вечером?',
  'Добавь картошку в список покупок.',
  'Включи музыку погромче, пожалуйста.',
  'Что у меня запланировано на выходные?',
  'Найди рецепт блинов на молоке.',
]

/** Что сказать о готовом образце: длительность и громкость. */
export function describeSample(s: VoiceSample): { text: string; warn: boolean } {
  const base = `Записано: ${s.seconds.toFixed(1)} с · ${Math.round(s.peak_db)} дБ`
  if (s.peak_db < -35) return { text: `${base} — тихо: подойди ближе или говори громче`, warn: true }
  return { text: base, warn: false }
}

function useSeries(actions: CoreActions, person: Person, onRecorded: () => void) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState({ text: '', warn: false })
  const stop = useRef(false)
  const start = async (device: string, series: boolean) => {
    stop.current = false
    setBusy(true)
    for (let fails = 0, count = person.samples.length; fails < 3 && !stop.current; ) {
      setNote({ text: `После сигнала скажи: «${PROMPTS[count % PROMPTS.length]}»`, warn: false })
      const out = await actions.recordSample(person.id, device)
      if (out.ok) [fails, count] = [0, count + 1]
      else fails += 1
      setNote(out.ok ? describeSample(out.sample) : { text: out.text, warn: true })
      if (out.ok) onRecorded()
      if (!series || count >= MAX_SERIES) break
      await new Promise((resolve) => setTimeout(resolve, PAUSE_MS))
    }
    setBusy(false)
  }
  return { busy, note, start, stop: () => (stop.current = true) }
}

type Props = { person: Person; modelReady: boolean; state: CoreState; actions: CoreActions; onRecorded: () => void }

export default function SampleRecorder({ person, modelReady, state, actions, onRecorded }: Props) {
  const speakers = (state.status?.devices ?? []).filter((d) => d.connected && (d.protocol ?? 0) >= 3)
  const [deviceId, setDeviceId] = useState('')
  const [series, setSeries] = useState(true)
  const rec = useSeries(actions, person, onRecorded)
  const device = speakers.some((d) => d.device_id === deviceId) ? deviceId : (speakers[0]?.device_id ?? '')
  const count = person.samples.length
  const hint = count < ENOUGH ? `Образцов ${count} из ${ENOUGH}: запиши ещё ${ENOUGH - count}` : `Образцов ${count} — хватит для узнавания`
  return (
    <div className="record-panel">
      <div className="cap">Голос с колонки</div>
      <label className="field">
        <span className="lbl">Колонка</span>
        <select className="val" value={device} disabled={rec.busy} onChange={(e) => setDeviceId(e.target.value)}>
          {speakers.length === 0 && <option value="">нет колонки с прошивкой 0.4+</option>}
          {speakers.map((d) => <option key={d.device_id} value={d.device_id}>{d.name || d.device_id}</option>)}
        </select>
      </label>
      <label className="link-head">
        <input type="checkbox" className="switch" checked={series} disabled={rec.busy} onChange={(e) => setSeries(e.target.checked)} />
        <span className="link-name">{`Подряд, до ${MAX_SERIES} образцов или «Стоп»`}</span>
      </label>
      <div className="record-buttons">
        <button type="button" className="btn" disabled={!device || !modelReady || rec.busy} onClick={() => void rec.start(device, series)}>{rec.busy ? 'Слушаю…' : 'Записать'}</button>
        {rec.busy && series && <button type="button" className="btn btn-plain" onClick={rec.stop}>Стоп</button>}
      </div>
      <div className={rec.note.warn ? 'set-note warn' : 'set-note'} role="status">{rec.note.text || (modelReady ? hint : 'Сначала скачай модель узнавания')}</div>
    </div>
  )
}
