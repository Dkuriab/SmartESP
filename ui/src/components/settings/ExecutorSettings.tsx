// Настройки исполнителя: имя, модель, рассуждение, описание, промпт, связи «Может передавать:»,
// итоговый промпт и «Удалить» (с подтверждением на месте). Входной (диспетчер) — частный случай: удалить нельзя.
import { useState } from 'react'
import type { ExecutorItem } from '../../schema/blocks'
import { executorUnavailable, isApplying, listExecutors, modelWithoutTools } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { ExecutorPatch } from '../../state/executors'
import type { CoreState } from '../../state/model'
import { APPLYING, CommitField, FinalPrompt, ModelField, PromptField, ReasoningField } from './ExecutorFields'
import LinkRows from './LinkRows'
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

export default function ExecutorSettings({ state, actions, executor: e }: Props) {
  const reachable = state.status?.ollama.reachable ?? true
  // пока изменение применяется, executors в настройках старые: новая правка затёрла бы его
  const applying = isApplying(state)
  const models = state.models ?? []
  const noTools = modelWithoutTools(state, e.model)
  const update = (patch: ExecutorPatch) => void actions.updateExecutor(e.id, patch)
  const final = state.config?.executor_prompts[e.id] ?? (e.entry ? state.config?.dispatcher_prompt : undefined)
  const others = listExecutors(state).filter((o) => o.id !== e.id)
  return (
    <div className="set">
      <h3 className="set-title">{`${e.entry ? '⚡️' : '🧠'} ${e.name || e.id}`}</h3>
      <div className="set-sub">{e.entry ? 'Исполнитель · отвечает первым' : 'Исполнитель'}</div>
      {/* key: после применения или отказа черновик берёт сохранённое значение */}
      <CommitField key={`name:${e.name}`} label="Имя" value={e.name} placeholder={e.id} required disabled={applying} onCommit={(name) => update({ name })} />
      <ModelField current={e.model} models={models} disabled={!reachable || applying} onPick={(model) => update({ model })} />
      {!reachable && <div className="set-note warn">Ollama недоступна</div>}
      {reachable && executorUnavailable(state, e.id) && <div className="set-note warn">модель недоступна</div>}
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
