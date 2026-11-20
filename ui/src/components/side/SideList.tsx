// Левая панель: «В работе», колонки, обработчики, исполнители, голос и коннекторы; клик выбирает блок.
// Работающее сейчас отмечено пульсирующей точкой с подписью (на узком экране схема мелкая);
// короткая работа отмечена не меньше 1,2 с.
import type { ReactNode } from 'react'
import { isApplying, listDevices, listExecutors, listStages, stagesLocked, stagesWith, voiceLabel } from '../../schema/blocks'
import { connectorToggle, connectorsLocked, listConnectors } from '../../schema/connectors'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Selection } from '../../state/model'
import AccessInfo from '../common/AccessInfo'
import TaskList from './TaskList'
import { steadyLive, useLiveGlow } from '../schema/useLiveGlow'
import './side.css'

type Props = { state: CoreState; actions: CoreActions }

type RowProps = { icon: string; label: string; sub?: ReactNode; target: Selection; props: Props; extra?: ReactNode; live?: string }

/** Строка списка: кнопка выбора блока, отметка «работает сейчас» и, возможно, свой элемент справа. */
function Row({ icon, label, sub, target, props, extra, live }: RowProps) {
  const { selected } = props.state
  const on = selected?.kind === target.kind && selected.id === target.id
  return (
    <div className={`row${on ? ' sel' : ''}`}>
      <button type="button" className="row-main" aria-pressed={on} onClick={() => props.actions.select(target)}>
        <span className="ico">{icon}</span>
        <span className="row-label" title={label}>{label}</span>
        {live && <span className="live-dot" role="img" aria-label={live} title={live} />}
        {sub !== undefined && <span className="sub">{sub}</span>}
      </button>
      {extra}
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title}>
      <div className="sec cap">{title}</div>
      {children}
    </section>
  )
}

function Devices(props: Props) {
  const devices = listDevices(props.state)
  return (
    <Section title={`Колонки ${devices.length}`}>
      {devices.length === 0 && <p className="side-none">Колонок пока нет</p>}
      {devices.map((d) => {
        const dot = <span role="img" className={d.connected ? 'dotg' : 'dotf'} aria-label={d.connected ? 'в сети' : 'не в сети'} />
        return <Row key={d.device_id} icon="🔊" label={d.name || d.device_id} sub={dot} target={{ kind: 'device', id: d.device_id }} props={props} />
      })}
    </Section>
  )
}

function Stages(props: Props) {
  const { state, actions } = props
  const locked = stagesLocked(state)
  return (
    <Section title="Обработчики">
      {listStages(state).map((s) => {
        const toggle = (
          <input
            type="checkbox"
            role="switch"
            className="switch"
            aria-label={s.title}
            checked={s.enabled}
            disabled={locked}
            onChange={(e) => void actions.setStages(stagesWith(state, s.kind, e.target.checked))}
          />
        )
        return <Row key={s.kind} icon={s.icon} label={s.title} target={{ kind: 'stage', id: s.kind }} props={props} extra={toggle} />
      })}
    </Section>
  )
}

/** Исполнители (входной первым) и «Добавить»: новый исполнитель сразу выбирается. */
function Executors(props: Props) {
  const { state, actions } = props
  const add = async () => {
    const id = await actions.addExecutor()
    if (id) actions.select({ kind: 'executor', id })
  }
  return (
    <Section title="Исполнители">
      {listExecutors(state).map((e) => {
        const now = state.live.executors[e.id]?.state
        const live = now === 'thinking' ? 'думает…' : now === 'speaking' ? 'говорит' : undefined
        return <Row key={e.id} icon={e.entry ? '⚡️' : '🧠'} label={e.name || e.id} sub={e.model || '—'} target={{ kind: 'executor', id: e.id }} props={props} live={live} />
      })}
      <button type="button" className="btn small side-add" disabled={isApplying(state) || state.config === null} onClick={() => void add()}>
        Добавить
      </button>
    </Section>
  )
}

/** Коннекторы с переключателем; упавший — красная точка. */
function Connectors(props: Props) {
  const { state, actions } = props
  const list = listConnectors(state)
  if (list.length === 0) return null
  const locked = connectorsLocked(state)
  return (
    <Section title="Коннекторы">
      {list.map((c) => {
        const toggle = (
          <input
            type="checkbox"
            role="switch"
            className="switch"
            aria-label={c.name}
            checked={c.enabled}
            disabled={locked}
            onChange={(e) => void actions.setConnectors(connectorToggle(c.id, e.target.checked), `${c.name}: ${e.target.checked ? 'включён' : 'выключен'}`)}
          />
        )
        const now = state.live.connectors[c.id]
        const sub = c.state === 'failed' ? <span role="img" className="dotr" aria-label="ошибка" /> : undefined
        return <Row key={c.id} icon="🧩" label={c.name} sub={sub} target={{ kind: 'connector', id: c.id }} props={props} extra={toggle} live={now ? `${now.tool}…` : undefined} />
      })}
    </Section>
  )
}

export default function SideList(props: Props) {
  const { state, actions } = props
  // точки работы держатся не меньше 1,2 с — как живая подсветка схемы
  const glow = useLiveGlow(state.live, state.connection === 'online')
  const working = { ...props, state: { ...state, live: steadyLive(glow) } }
  const connectorName = (id: string) => listConnectors(state).find((c) => c.id === id)?.name
  return (
    <>
      <TaskList tasks={state.tasks} connectorName={connectorName} />
      <Devices {...props} />
      <Stages {...props} />
      <Executors {...working} />
      <Section title="Голос">
        <Row icon="🔈" label="Голос" sub={voiceLabel(state) ?? '—'} target={{ kind: 'voice', id: 'voice' }} props={props} />
      </Section>
      <Connectors {...working} />
      <AccessInfo loadAccess={actions.loadAccess} online={state.connection === 'online'} />
    </>
  )
}
