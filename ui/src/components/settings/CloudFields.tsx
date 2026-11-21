// Где работает исполнитель (Ollama на Mac или облачный сервис), облачная модель и ключ сервиса.
import { useEffect, useState } from 'react'
import type { CloudModel, Model } from '../../state/model'

export const CLOUD = 'cloud'
/** Модель по умолчанию при переходе в облако: быстрая, недорогая, умеет инструменты. */
export const DEFAULT_CLOUD_MODEL = 'google/gemini-2.5-flash'
const DEFAULT_LOCAL_MODEL = 'gpt-oss:20b'

/** Модель при смене места: облако — DEFAULT_CLOUD_MODEL; Mac — gpt-oss:20b, если скачана, иначе первая. */
export function modelForKind(kind: string, local: Model[]): string {
  if (kind === CLOUD) return DEFAULT_CLOUD_MODEL
  return local.find((m) => m.name === DEFAULT_LOCAL_MODEL)?.name ?? local[0]?.name ?? DEFAULT_LOCAL_MODEL
}

type KindProps = { kind: string; service: string; disabled: boolean; onPick: (kind: string) => void }

export function KindField({ kind, service, disabled, onPick }: KindProps) {
  return (
    <label className="field">
      <span className="lbl">Где работает</span>
      <select className="val" value={kind === CLOUD ? CLOUD : 'ollama'} disabled={disabled} onChange={(e) => onPick(e.target.value)}>
        <option value="ollama">На Mac (Ollama)</option>
        <option value={CLOUD}>{`В облаке (${service})`}</option>
      </select>
    </label>
  )
}

/** «$0.3 / $2.5 за 1 млн токенов» или пусто, если цены неизвестны. */
export function priceText(m: CloudModel): string {
  if (m.prompt_price == null || m.completion_price == null) return ''
  if (m.prompt_price === 0 && m.completion_price === 0) return 'бесплатно'
  return `$${m.prompt_price} вход / $${m.completion_price} ответ за 1 млн токенов`
}

/** Пометка к выбранной модели: цена, нет инструментов, нет в списке сервиса. */
export function cloudModelNote(current: string, models: CloudModel[]): { text: string; warn: boolean } {
  if (models.length === 0) return { text: '', warn: false }
  const found = models.find((m) => m.id === current)
  if (!found) return { text: 'такой модели нет в списке сервиса', warn: true }
  if (!found.tools) return { text: 'модель не умеет инструменты: заметки, таймеры и передача задач не сработают', warn: true }
  return { text: priceText(found), warn: false }
}

type ModelProps = {
  current: string
  disabled: boolean
  load: () => Promise<CloudModel[]>
  onPick: (model: string) => void
}

/** Модель сервиса: поле с подсказками из списка (поиск по набору); сохраняется по Enter или уходу с поля. */
export function CloudModelField({ current, disabled, load, onPick }: ModelProps) {
  const [models, setModels] = useState<CloudModel[]>([])
  const [draft, setDraft] = useState(current)
  useEffect(() => {
    let alive = true
    void load().then((list) => alive && setModels(list))
    return () => {
      alive = false
    }
  }, [load])
  const save = () => {
    const id = draft.trim()
    if (!id || id === current) setDraft(current)
    else onPick(id)
  }
  const note = cloudModelNote(current, models)
  return (
    <>
      <label className="field">
        <span className="lbl">Модель</span>
        <input className="val" list="cloud-models" value={draft} disabled={disabled} placeholder={DEFAULT_CLOUD_MODEL}
          onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} onBlur={save} />
      </label>
      <datalist id="cloud-models">
        {models.map((m) => (
          <option key={m.id} value={m.id}>{m.tools ? m.name : `${m.name} (без инструментов)`}</option>
        ))}
      </datalist>
      {note.text && <div className={note.warn ? 'set-note warn' : 'set-note'}>{note.text}</div>}
    </>
  )
}

type KeyProps = { service: string; isSet: boolean; disabled: boolean; onSave: (key: string) => void }

/** Ключ сервиса: задан — «•••» и «Заменить»; поле пароля, «Сохранить ключ»; предупреждение про облако. */
export function CloudKeyField({ service, isSet, disabled, onSave }: KeyProps) {
  const [draft, setDraft] = useState('')
  const save = () => {
    onSave(draft.trim())
    setDraft('')
  }
  return (
    <div className="field field-block">
      <label className="field">
        <span className="lbl">{`Ключ ${service}`}</span>
        <input className="val" type="password" autoComplete="off" value={draft} disabled={disabled}
          placeholder={isSet ? 'задан — введите новый, чтобы заменить' : 'не задан'} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <button type="button" className="btn" disabled={disabled || !draft.trim()} onClick={save}>Сохранить ключ</button>
      {!isSet && <div className="set-note warn">{`Без ключа модель не ответит: ключ — на сайте ${service} в разделе Keys`}</div>}
      <div className="set-note">Текст разговоров с этой моделью уходит в облако.</div>
    </div>
  )
}
