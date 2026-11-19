// Вкладка «Ядро»: состояние, перезапуск и остановка, модели в памяти, журнал, кнопки приложения.
import { useEffect, useState } from 'react'
import { hasBridge } from '../../api/bridge'
import type { CoreActions } from '../../state/actions'
import type { CoreInfo } from '../../state/coreActions'
import { useLogLines } from '../../state/logs'
import type { CoreState } from '../../state/model'
import AppButtons from './AppButtons'
import CoreControls from './CoreControls'
import LoadedModels from './LoadedModels'
import LogView from './LogView'
import { formatUptime } from './uptime'
import './core.css'

type Props = { state: CoreState; actions: CoreActions }

function Facts({ state, info }: { state: CoreState; info: CoreInfo | null }) {
  const status = state.status
  const uptime = status?.uptime_s ?? info?.uptime_s
  const rows: Array<[string, string]> = [
    ['Версия', status?.version ?? info?.version ?? '—'],
    ['Работает', uptime === undefined ? '—' : formatUptime(uptime)],
    ['Порт', info ? String(info.port) : '—'],
    ['Папка данных', info?.data_dir ?? '—'],
  ]
  return (
    <dl className="core-facts">
      {rows.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function CoreTab({ state, actions }: Props) {
  const [info, setInfo] = useState<CoreInfo | null>(null)
  const online = state.connection === 'online'
  const { loadCoreInfo } = actions
  useEffect(() => {
    if (online) void loadCoreInfo().then((data) => data && setInfo(data))
  }, [online, loadCoreInfo])
  const logs = useLogLines(actions.watchLogs)
  const inApp = hasBridge()
  const ollama = state.status?.ollama
  return (
    <div className="panel core-full">
      <div className="core-side">
        <div className="cap">Ядро</div>
        <Facts state={state} info={info} />
        <CoreControls
          online={online}
          busy={state.restarting || state.status?.state === 'stopping'}
          onRestart={() => void actions.restart()}
          onStop={actions.stopCore}
          inApp={inApp}
        />
        <div className="cap">Модели в памяти</div>
        <LoadedModels loaded={ollama && ollama.reachable ? ollama.loaded : null} onUnload={actions.unloadModel} />
        {inApp && <div className="cap">Файлы</div>}
        {inApp && <AppButtons onOpen={actions.openInApp} />}
      </div>
      <LogView lines={logs.lines} online={logs.online} />
    </div>
  )
}
