// Исполнитель на LM Studio: модель из списка сервера (загружена ли, умеет ли инструменты), адрес и ключ сервера.
import { useEffect, useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState, LmStudioList, LmStudioModel } from '../../state/model'
import { SecretField } from './CloudFields'
import { CommitField } from './ExecutorFields'

const DEFAULT_URL = 'http://localhost:1234'
const EMPTY: LmStudioList = { models: [], error: '' }

/** Подпись модели: имя · загружена · инструменты (или без родных инструментов). */
export function lmStudioModelLabel(m: LmStudioModel): string {
  const tools = m.tools === true ? 'инструменты' : m.tools === false ? 'без родных инструментов' : ''
  return [m.name, m.loaded ? 'загружена' : '', tools].filter(Boolean).join(' · ')
}

/** Модель при переходе на LM Studio: загруженная, иначе первая из списка, иначе fallback. */
export function pickLmStudioModel(models: LmStudioModel[], fallback: string): string {
  return models.find((m) => m.loaded)?.id ?? models[0]?.id ?? fallback
}

/** Пометка к выбранной модели: нет в LM Studio, не загружена, без родных инструментов, загружена. */
export function lmStudioModelNote(current: string, models: LmStudioModel[]): { text: string; warn: boolean } {
  if (models.length === 0) return { text: '', warn: false }
  const found = models.find((m) => m.id === current)
  if (!found) return { text: 'такой модели нет в LM Studio — скачайте её там или выберите другую', warn: true }
  if (found.tools === false) return { text: 'у модели нет родной поддержки инструментов: LM Studio даст их общим форматом, вызовы могут быть хуже', warn: true }
  if (found.loaded === false) return { text: 'модель не загружена: LM Studio загрузит её при первом ходе (если включена загрузка по запросу — JIT)', warn: false }
  return { text: found.loaded ? 'загружена в LM Studio' : '', warn: false }
}

type ModelProps = { current: string; list: LmStudioList; disabled: boolean; onPick: (model: string) => void }

/** Модель: список сервера; сервер не ответил — ввод id вручную (по Enter или уходу с поля). */
export function LmStudioModelField({ current, list, disabled, onPick }: ModelProps) {
  const [draft, setDraft] = useState(current)
  const note = lmStudioModelNote(current, list.models)
  const known = list.models.some((m) => m.id === current)
  const save = () => (draft.trim() && draft.trim() !== current ? onPick(draft.trim()) : setDraft(current))
  return (
    <>
      <label className="field">
        <span className="lbl">Модель</span>
        {list.models.length > 0 ? (
          <select className="val" value={current} disabled={disabled} onChange={(e) => onPick(e.target.value)}>
            {!known && <option value={current}>{`${current} (нет в LM Studio)`}</option>}
            {list.models.map((m) => (
              <option key={m.id} value={m.id}>{lmStudioModelLabel(m)}</option>
            ))}
          </select>
        ) : (
          <input className="val" value={draft} disabled={disabled} placeholder="qwen/qwen3-8b" onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} onBlur={save} />
        )}
      </label>
      {list.error && <div className="set-note warn">{list.error}</div>}
      {note.text && <div className={note.warn ? 'set-note warn' : 'set-note'}>{note.text}</div>}
    </>
  )
}

type ServerProps = { baseUrl: string; keySet: boolean; disabled: boolean; actions: CoreActions }

/** Адрес сервера LM Studio и ключ (нужен, только если в LM Studio включена проверка ключа). */
export function LmStudioServerFields({ baseUrl, keySet, disabled, actions }: ServerProps) {
  return (
    <div className="field field-block">
      <CommitField key={`lms:${baseUrl}`} label="Адрес LM Studio" value={baseUrl} placeholder={DEFAULT_URL} required disabled={disabled}
        onCommit={(base_url) => void actions.setLmStudio({ base_url }, 'Адрес LM Studio')} />
      <SecretField label="Ключ LM Studio" isSet={keySet} disabled={disabled} placeholder="не задан — нужен, если в LM Studio включена проверка ключа"
        onSave={(api_key) => void actions.setLmStudio({ api_key }, api_key ? 'Ключ LM Studio' : 'Ключ LM Studio убран')} />
      {keySet && <div className="set-note">Ключ задан: смена адреса сбрасывает ключ — введите его снова.</div>}
      <div className="set-note">В LM Studio включите сервер: Developer → Start Server.</div>
    </div>
  )
}

type BlockProps = { state: CoreState; actions: CoreActions; current: string; applying: boolean; onPick: (model: string) => void }

/** Модель и сервер LM Studio; список моделей запрашивается при открытии и после смены адреса. */
export function LmStudioBlock({ state, actions, current, applying, onPick }: BlockProps) {
  const [list, setList] = useState<LmStudioList>(EMPTY)
  const settings = (state.config?.effective.lmstudio ?? {}) as { base_url?: unknown; api_key?: unknown }
  const baseUrl = typeof settings.base_url === 'string' ? settings.base_url : DEFAULT_URL
  const { loadLmStudioModels } = actions
  useEffect(() => {
    let alive = true
    void loadLmStudioModels().then((loaded) => alive && setList(loaded))
    return () => {
      alive = false
    }
  }, [loadLmStudioModels, baseUrl])
  return (
    <>
      <LmStudioModelField key={`${current}:${list.models.length}`} current={current} list={list} disabled={applying} onPick={onPick} />
      <LmStudioServerFields baseUrl={baseUrl} keySet={Boolean(settings.api_key)} disabled={applying} actions={actions} />
    </>
  )
}
