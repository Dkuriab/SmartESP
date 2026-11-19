// Правая панель: настройки блока, выбранного на схеме или в списке.
import { isApplying, listDevices, listExecutors, listStages, stagesLocked, stagesWith } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import { ConnectorPanel } from './ConnectorSettings'
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
    const id = device.device_id
    return (
      <DeviceSettings
        key={`${id}:${device.name}`}
        device={device}
        onRename={(name) => void actions.renameDevice(id, name)}
        filePhase={state.files[id]}
        onPlayFile={(file) => void actions.playFile(id, file)}
        onStopFile={() => void actions.stopFile(id)}
      />
    )
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
  if (selected?.kind === 'connector') return <ConnectorPanel state={state} actions={actions} id={selected.id} hint={hint} />
  return hint
}
