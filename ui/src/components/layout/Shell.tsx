// Каркас экрана: плавающие панели поверх холста в точку; на узком экране
// боковые панели открываются поверх схемы кнопками «Список» и «Настройки».
import { useState } from 'react'
import { listExecutors } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import Notice from '../common/Notice'
import CoreTab from '../core/CoreTab'
import RestartBanner from '../common/RestartBanner'
import TokenScreen from '../common/TokenScreen'
import TrainingTab from '../training/TrainingTab'
import Feed from '../feed/Feed'
import SchemaView from '../schema/SchemaView'
import SettingsPanel from '../settings/SettingsPanel'
import SideList from '../side/SideList'
import type { Overlay, Tab } from '../top/TopBar'
import TopBar from '../top/TopBar'
import './layout.css'

type Props = { state: CoreState; actions: CoreActions }

export default function Shell({ state, actions }: Props) {
  const [tab, setTab] = useState<Tab>('schema')
  // открытая поверх схемы панель (только на узком экране; на широком панели видны всегда)
  const [overlay, setOverlay] = useState<Overlay | null>(null)
  const full = tab !== 'schema'
  const open = (which: Overlay) => (overlay === which ? ' open' : '')
  // выбор блока в списке или на схеме открывает его настройки (на широком экране они и так видны)
  const picking: CoreActions = {
    ...actions,
    select(selected) {
      actions.select(selected)
      if (selected) setOverlay('settings')
    },
  }
  return (
    <main className="canvas">
      {!full && (
        <aside className={`panel left${open('list')}`} aria-label="Список">
          <SideList state={state} actions={picking} />
        </aside>
      )}
      {!full && (
        <section className="schema" aria-label="Схема">
          <SchemaView state={state} actions={picking} />
        </section>
      )}
      {!full && (
        <aside className={`panel right${open('settings')}`} aria-label="Настройки">
          <SettingsPanel state={state} actions={actions} />
        </aside>
      )}
      {tab === 'core' && <CoreTab state={state} actions={actions} />}
      {tab === 'training' && <TrainingTab state={state} actions={actions} />}
      {tab !== 'core' && tab !== 'training' && (
        <Feed turns={state.turns} executors={listExecutors(state)} selectedId={state.selectedTurnId} onSelect={actions.selectTurn} full={full} />
      )}
      <TopBar state={state} tab={tab} onTab={setTab} overlay={full ? undefined : overlay} onOverlay={setOverlay} />
      {state.status?.restart_required && (
        <RestartBanner onRestart={() => void actions.restart()} restarting={state.restarting} online={state.connection === 'online'} />
      )}
      {state.notice && <Notice notice={state.notice} onDismiss={actions.dismissNotice} />}
      {state.connection === 'unauthorized' && <TokenScreen onToken={actions.setToken} />}
    </main>
  )
}
