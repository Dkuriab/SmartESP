// Правая панель: настройки блока, выбранного на схеме или в списке.
import type { ReactElement } from 'react'
import { isApplying, listDevices, listExecutors, listStages, stagesLocked, stagesWith } from '../../schema/blocks'
import { connectorsLocked, connectorsWith, listConnectors } from '../../schema/connectors'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import ConnectorSettings from './ConnectorSettings'
import DeviceSettings from './DeviceSettings'
import ExecutorSettings from './ExecutorSettings'
import StageSettings from './StageSettings'
import VoiceSettings from './VoiceSettings'
import './settings.css'

type Props = { state: CoreState; actions: CoreActions }

const HINT = 'Выберите блок на схеме или в списке'

export default function SettingsPanel({ state, actions }: Props) {
  const hint = <p className="set-hint">{HINT}</p>
  const { selected } = state
  if (selected?.kind === 'device') {
    const device = listDevices(state).find((d) => d.device_id === selected.id)
    if (!device) return hint
    // key: черновик сбрасывается при смене колонки, переименовании извне и после отказа
    return <DeviceSettings key={`${device.device_id}:${device.name}`} device={device} onRename={(name) => void actions.renameDevice(device.device_id, name)} />
  }
  if (selected?.kind === 'stage') {
    const stage = listStages(state).find((s) => s.kind === selected.id)
    if (!stage) return hint
    const onToggle = (on: boolean) => void actions.setStages(stagesWith(state, stage.kind, on))
    return <StageSettings stage={stage} applying={isApplying(state)} locked={stagesLocked(state)} onToggle={onToggle} />
  }
  if (selected?.kind === 'executor' || selected?.kind === 'dispatcher') {
    // прежний выбор «dispatcher» — это входной исполнитель
    const list = listExecutors(state)
    const executor = selected.kind === 'dispatcher' ? list.find((e) => e.entry) : list.find((e) => e.id === selected.id)
    if (!executor) return hint
    // key: черновики полей не переходят к другому исполнителю
    return <ExecutorSettings key={executor.id} state={state} actions={actions} executor={executor} />
  }
  if (selected?.kind === 'voice') return <VoiceSettings state={state} actions={actions} />
  if (selected?.kind === 'connector') return <Connector state={state} actions={actions} id={selected.id} hint={hint} />
  return hint
}

function Connector({ state, actions, id, hint }: Props & { id: string; hint: ReactElement }) {
  const connector = listConnectors(state).find((c) => c.id === id)
  if (!connector) return hint
  const onToggle = (on: boolean) =>
    void actions.setConnectors(connectorsWith(state, id, on), `${connector.name}: ${on ? 'включён' : 'выключен'}`)
  return (
    <ConnectorSettings
      connector={connector}
      applying={isApplying(state)}
      locked={connectorsLocked(state)}
      liveTool={state.live.connectors[id]?.tool}
      onToggle={onToggle}
    />
  )
}
