// Настройки голоса: состояние текущего и каталог по видам (Piper, Silero, Vosk).
import { isApplying, voiceLabel } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState, Voice } from '../../state/model'
import VoiceRow from './VoiceRow'
import { progressText } from './voice'

type Props = { state: CoreState; actions: CoreActions }

const KIND_TITLES: Record<string, string> = { piper: 'Piper', silero: 'Silero', vosk: 'Vosk' }

/** Голоса по видам: сначала известные виды по порядку, затем прочие. */
function groups(voices: Voice[]): Array<[string, Voice[]]> {
  const kinds = [...Object.keys(KIND_TITLES), ...voices.map((v) => v.kind)]
  return [...new Set(kinds)]
    .map((kind): [string, Voice[]] => [kind, voices.filter((v) => v.kind === kind)])
    .filter(([, list]) => list.length > 0)
}

/** Состояние нужного голоса: готов / качается N% / ошибка с текстом. */
function stateText(state: CoreState): string {
  const live = state.status?.voice
  if (!live?.kind) return ''
  if (live.state === 'ready') return 'готов'
  if (live.state === 'failed') return live.error ? `ошибка: ${live.error}` : 'ошибка'
  if (live.state === 'missing') return 'не скачан'
  const progress = progressText(state.downloads[`${live.kind}/${live.voice ?? ''}`])
  return progress ? `качается ${progress}` : 'качается…'
}

export default function VoiceSettings({ state, actions }: Props) {
  const applying = isApplying(state)
  const failed = state.status?.voice?.state === 'failed'
  return (
    <div className="set">
      <h3 className="set-title">🔈 Голос</h3>
      <div className="set-sub">Озвучивание ответов</div>
      <div className="field">
        <span className="lbl">Текущий</span>
        <span className="val-text">{voiceLabel(state) ?? '—'}</span>
      </div>
      <div className={`set-note${failed ? ' bad' : ''}`}>{stateText(state)}</div>
      {!state.voices && <p className="set-hint">Загрузка…</p>}
      {groups(state.voices ?? []).map(([kind, list]) => (
        <section key={kind} className="voice-kind" aria-label={KIND_TITLES[kind] ?? kind}>
          <h4 className="cap">{KIND_TITLES[kind] ?? kind}</h4>
          <ul className="voice-list">
            {list.map((v) => (
              <VoiceRow key={v.voice} voice={v} download={state.downloads[`${v.kind}/${v.voice}`]} applying={applying} actions={actions} />
            ))}
          </ul>
        </section>
      ))}
      <p className="set-fine">Голоса Silero — только для некоммерческого использования.</p>
    </div>
  )
}
