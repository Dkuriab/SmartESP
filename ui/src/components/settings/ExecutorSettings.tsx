// Настройки исполнителя: имя, модель, рассуждение, описание, промпт, связи «Может передавать:»,
// итоговый промпт и «Удалить» (с подтверждением на месте). Входной (диспетчер) — частный случай: удалить нельзя.
import { useState } from 'react'
import type { ExecutorItem } from '../../schema/blocks'
import { executorUnavailable, isApplying, listExecutors, modelWithoutTools } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { ExecutorPatch } from '../../state/executors'
import type { CoreState } from '../../state/model'
import { CLOUD, CloudKeyField, CloudModelField, KindField, LMSTUDIO, modelForKind } from './CloudFields'
import { APPLYING, CommitField, FinalPrompt, ModelField, PromptField, ReasoningField } from './ExecutorFields'
import LinkRows from './LinkRows'
import { LmStudioBlock, pickLmStudioModel } from './LmStudioFields'
import SpeechSettings from './SpeechSettings'

type Props = { state: CoreState; actions: CoreActions; executor: ExecutorItem }

type RemoveProps = { name: string; disabled: boolean; onRemove: () => void }

/**
 * «Удалить» с подтверждением на месте: первый клик спрашивает, второй удаляет.
 * Не системный диалог подтверждения: в WKWebView приложения без делегата он всегда отвечает «нет».
 */
function RemoveButton({ name, disabled, onRemove }: RemoveProps) {
  const [asking, setAsking] = useState(false)
  if (!asking) {
    return (
      <button type="button" className="btn btn-danger" disabled={disabled} onClick={() => setAsking(true)}>
        Удалить
      </button>
    )
  }
  return (
    <div className="remove-ask">
      <span className="set-text">{`Удалить «${name}»? Связи на него тоже уберутся.`}</span>
      <button type="button" className="btn btn-danger" disabled={disabled} onClick={onRemove}>
        Удалить
      </button>
      <button type="button" className="btn btn-plain" onClick={() => setAsking(false)}>
        Отмена
      </button>
    </div>
  )
}

type GenderProps = { gender: 'male' | 'female'; disabled: boolean; onPick: (gender: 'male' | 'female') => void }

/** Род ассистента: в каком роде он говорит о себе (домовой или домовая). */
function GenderField({ gender, disabled, onPick }: GenderProps) {
  return (
    <label className="field">
      <span className="lbl">Пол</span>
      <select className="val" value={gender} disabled={disabled} onChange={(ev) => onPick(ev.target.value as 'male' | 'female')}>
        <option value="male">Мужской — домовой</option>
        <option value="female">Женский — домовая</option>
      </select>
    </label>
  )
}

/** Ошибка прогрева исполнителя из status (нет — пусто). */
function warmError(state: CoreState, id: string): string {
  return state.status?.executors?.find((x) => x.id === id)?.error ?? ''
}

type ModelProps = Props & { applying: boolean }

/** Где работает, модель и (для облака и LM Studio) настройки сервиса; предупреждения о недоступности. */
function ModelBlock({ state, actions, executor: e, applying }: ModelProps) {
  const reachable = state.status?.ollama.reachable ?? true
  const ollama = e.kind !== CLOUD && e.kind !== LMSTUDIO
  const settings = (state.config?.effective.cloud ?? {}) as { name?: unknown; api_key?: unknown }
  const service = typeof settings.name === 'string' && settings.name ? settings.name : 'OpenRouter'
  const update = (patch: ExecutorPatch) => void actions.updateExecutor(e.id, patch)
  const pickKind = (kind: string) => {
    if (kind !== LMSTUDIO) return update({ kind, model: modelForKind(kind, state.models ?? []) })
    void actions.loadLmStudioModels().then((list) => update({ kind, model: pickLmStudioModel(list.models, e.model) }))
  }
  const unavailable = executorUnavailable(state, e.id)
  const pick = (model: string) => update({ model })
  return (
    <>
      <KindField kind={e.kind} service={service} disabled={applying} onPick={pickKind} />
      {e.kind === CLOUD && <CloudModelField key={e.model} current={e.model} disabled={applying} load={actions.loadCloudModels} onPick={pick} />}
      {e.kind === LMSTUDIO && <LmStudioBlock state={state} actions={actions} current={e.model} applying={applying} onPick={pick} />}
      {ollama && <ModelField current={e.model} models={state.models ?? []} disabled={!reachable || applying} onPick={pick} />}
      {ollama && !reachable && <div className="set-note warn">Ollama недоступна</div>}
      {ollama && reachable && unavailable && <div className="set-note warn">модель недоступна</div>}
      {!ollama && unavailable && <div className="set-note warn">{warmError(state, e.id) || 'модель недоступна'}</div>}
      {e.kind === CLOUD && <CloudKeyField service={service} isSet={Boolean(settings.api_key)} disabled={applying} onSave={(key) => void actions.setCloudKey(key)} />}
    </>
  )
}

export default function ExecutorSettings({ state, actions, executor: e }: Props) {
  // пока изменение применяется, executors в настройках старые: новая правка затёрла бы его
  const applying = isApplying(state)
  const noTools = modelWithoutTools(state, e.model)
  const update = (patch: ExecutorPatch) => void actions.updateExecutor(e.id, patch)
  const final = state.config?.executor_prompts[e.id] ?? (e.entry ? state.config?.dispatcher_prompt : undefined)
  const others = listExecutors(state).filter((o) => o.id !== e.id)
  return (
    <div className="set">
      <h3 className="set-title">{`${e.entry ? '⚡️' : '🧠'} ${e.name || e.id}`}</h3>
      <div className="set-sub">{e.entry ? 'Ассистент — домовой, отвечает первым' : 'Исполнитель — помогает ассистенту'}</div>
      {/* key: после применения или отказа черновик берёт сохранённое значение */}
      <CommitField key={`name:${e.name}`} label={e.entry ? 'Имя ассистента' : 'Имя'} value={e.name} placeholder={e.id} required disabled={applying} onCommit={(name) => update({ name })} />
      {e.entry && <GenderField gender={e.gender} disabled={applying} onPick={(gender) => update({ gender })} />}
      <ModelBlock state={state} actions={actions} executor={e} applying={applying} />
      {applying && <div className="set-note">{APPLYING}</div>}
      <ReasoningField current={e.reasoning} model={e.model} disabled={applying} onPick={(reasoning) => update({ reasoning })} />
      <CommitField key={`desc:${e.description}`} label="Описание" value={e.description} placeholder="Когда ко мне обращаться" disabled={applying} onCommit={(description) => update({ description })} />
      <PromptField key={e.systemPrompt} current={e.systemPrompt} applying={applying} onSave={(systemPrompt) => update({ systemPrompt })} />
      <LinkRows executor={e} others={others} disabled={applying} noTools={noTools} onLink={(to, on, when) => void actions.setLink(e.id, to, on, when)} />
      {e.entry && <SpeechSettings state={state} actions={actions} />}
      {final !== undefined && <FinalPrompt text={final} />}
      {!e.entry && <RemoveButton name={e.name || e.id} disabled={applying} onRemove={() => void actions.removeExecutor(e.id)} />}
    </div>
  )
}
