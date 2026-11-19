// Правая панель: настройки блока, выбранного на схеме или в списке.
import { isApplying, listDevices, listStages, stagesLocked, stagesWith } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import DeviceSettings from './DeviceSettings'
import DispatcherSettings from './DispatcherSettings'
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
  if (selected?.kind === 'dispatcher') return <DispatcherSettings state={state} actions={actions} />
  if (selected?.kind === 'voice') return <VoiceSettings state={state} actions={actions} />
  return hint
}
