// Два переключателя речи: Кузя заговаривает сам и слушает после своего вопроса.
import { isApplying } from '../../schema/blocks'
import type { CoreActions } from '../../state/actions'
import type { CoreState } from '../../state/model'

type Props = { state: CoreState; actions: CoreActions }

type Key = 'proactive' | 'listen_after_question'

const ROWS: Array<{ key: Key; label: string; description: string }> = [
  { key: 'proactive', label: 'Кузя может заговорить сам', description: 'Напоминания и поздние ответы' },
  { key: 'listen_after_question', label: 'Слушать после вопроса', description: 'Ответ на вопрос Кузи без слова активации' },
]

/** Значение флага из config.effective.speech; по умолчанию включено. */
function flag(state: CoreState, key: Key): boolean {
  const speech = state.config?.effective.speech as Partial<Record<Key, boolean>> | undefined
  return speech?.[key] ?? true
}

export default function SpeechSettings({ state, actions }: Props) {
  // пока правка применяется, config старый: новая затёрла бы её
  const disabled = isApplying(state) || state.config === null
  return (
    <div className="set-speech">
      {ROWS.map((row) => (
        <label key={row.key} className="link-head" title={row.description}>
          <input
            type="checkbox"
            className="switch"
            checked={flag(state, row.key)}
            disabled={disabled}
            onChange={(e) => void actions.patchConfig({ speech: { [row.key]: e.target.checked } }, row.label)}
          />
          <span className="link-name">{row.label}</span>
        </label>
      ))}
    </div>
  )
}
