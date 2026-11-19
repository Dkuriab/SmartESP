// Левая панель: колонки, обработчики, диспетчер и голос; клик выбирает блок.
import type { ReactNode } from 'react'
import { dispatcherInfo, isApplying, listDevices, listStages, stagesWith, voiceLabel } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Selection } from '../../state/model'
import AccessInfo from '../common/AccessInfo'
import './side.css'

type Props = { state: CoreState; actions: CoreActions }

type RowProps = { icon: string; label: string; sub?: ReactNode; target: Selection; props: Props; extra?: ReactNode }

/** Строка списка: кнопка выбора блока и, возможно, свой элемент справа. */
function Row({ icon, label, sub, target, props, extra }: RowProps) {
  const { selected } = props.state
  const on = selected?.kind === target.kind && selected.id === target.id
  return (
    <div className={`row${on ? ' sel' : ''}`}>
      <button type="button" className="row-main" aria-pressed={on} onClick={() => props.actions.select(target)}>
        <span className="ico">{icon}</span>
        <span className="row-label" title={label}>{label}</span>
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
  const applying = isApplying(state)
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
            disabled={applying}
            onChange={(e) => void actions.setStages(stagesWith(state, s.kind, e.target.checked))}
          />
        )
        return <Row key={s.kind} icon={s.icon} label={s.title} target={{ kind: 'stage', id: s.kind }} props={props} extra={toggle} />
      })}
    </Section>
  )
}

export default function SideList(props: Props) {
  const { state, actions } = props
  return (
    <>
      <Devices {...props} />
      <Stages {...props} />
      <Section title="Диспетчер">
        <Row icon="⚡️" label="Диспетчер" sub={dispatcherInfo(state)?.model || '—'} target={{ kind: 'dispatcher', id: 'dispatcher' }} props={props} />
      </Section>
      <Section title="Голос">
        <Row icon="🔈" label="Голос" sub={voiceLabel(state) ?? '—'} target={{ kind: 'voice', id: 'voice' }} props={props} />
      </Section>
      <AccessInfo loadAccess={actions.loadAccess} online={state.connection === 'online'} />
    </>
  )
}
