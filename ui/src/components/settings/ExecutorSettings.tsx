// Настройки исполнителя: имя, модель, описание, промпт, связи «Может передавать:»,
// итоговый промпт и «Удалить». Входной (диспетчер) — частный случай: удалить нельзя.
import type { ExecutorItem } from '../../schema/blocks'
import { isApplying, listExecutors } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { ExecutorPatch } from '../../state/executors'
import type { CoreState } from '../../state/model'
import { APPLYING, CommitField, FinalPrompt, ModelField, PromptField } from './ExecutorFields'
import LinkRows from './LinkRows'

type Props = { state: CoreState; actions: CoreActions; executor: ExecutorItem }

type RemoveProps = { name: string; disabled: boolean; onRemove: () => void }

/** «Удалить» с подтверждением через window.confirm. */
function RemoveButton({ name, disabled, onRemove }: RemoveProps) {
  const ask = () => {
    if (window.confirm(`Удалить исполнителя «${name}»? Связи других исполнителей на него тоже уберутся.`)) onRemove()
  }
  return (
    <button type="button" className="btn btn-danger" disabled={disabled} onClick={ask}>
      Удалить
    </button>
  )
}

export default function ExecutorSettings({ state, actions, executor: e }: Props) {
  const reachable = state.status?.ollama.reachable ?? true
  // пока изменение применяется, executors в настройках старые: новая правка затёрла бы его
  const applying = isApplying(state)
  const models = state.models ?? []
  const noTools = models.find((m) => m.name === e.model)?.supports_tools === false
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
      {applying && <div className="set-note">{APPLYING}</div>}
      <CommitField key={`desc:${e.description}`} label="Описание" value={e.description} placeholder="Когда ко мне обращаться" disabled={applying} onCommit={(description) => update({ description })} />
      <PromptField key={e.systemPrompt} current={e.systemPrompt} applying={applying} onSave={(systemPrompt) => update({ systemPrompt })} />
      <LinkRows executor={e} others={others} disabled={applying} noTools={noTools} onLink={(to, on, when) => void actions.setLink(e.id, to, on, when)} />
      {final !== undefined && <FinalPrompt text={final} />}
      {!e.entry && <RemoveButton name={e.name || e.id} disabled={applying} onRemove={() => void actions.removeExecutor(e.id)} />}
    </div>
  )
}
