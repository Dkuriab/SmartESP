// Каркас экрана: плавающие панели поверх холста в точку.
import { useState } from 'react'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'
import Notice from '../common/Notice'
import RestartBanner from '../common/RestartBanner'
import TokenScreen from '../common/TokenScreen'
import Feed from '../feed/Feed'
import SchemaView from '../schema/SchemaView'
import SettingsPanel from '../settings/SettingsPanel'
import SideList from '../side/SideList'
import type { Tab } from '../top/TopBar'
import TopBar from '../top/TopBar'
import './layout.css'

type Props = { state: CoreState; actions: CoreActions }

export default function Shell({ state, actions }: Props) {
  const [tab, setTab] = useState<Tab>('schema')
  const full = tab === 'feed'
  return (
    <main className="canvas">
      {!full && (
        <aside className="panel left" aria-label="Список">
          <SideList state={state} actions={actions} />
        </aside>
      )}
      {!full && (
        <section className="schema" aria-label="Схема">
          <SchemaView state={state} actions={actions} />
        </section>
      )}
      {!full && (
        <aside className="panel right" aria-label="Настройки">
          <SettingsPanel state={state} actions={actions} />
        </aside>
      )}
      <Feed turns={state.turns} selectedId={state.selectedTurnId} onSelect={actions.selectTurn} full={full} />
      <TopBar state={state} tab={tab} onTab={setTab} />
      {state.status?.restart_required && (
        <RestartBanner onRestart={() => void actions.restart()} restarting={state.restarting} online={state.connection === 'online'} />
      )}
      {state.notice && <Notice notice={state.notice} onDismiss={actions.dismissNotice} />}
      {state.connection === 'unauthorized' && <TokenScreen onToken={actions.setToken} />}
    </main>
  )
}
