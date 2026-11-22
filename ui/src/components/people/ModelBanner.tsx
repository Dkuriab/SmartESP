// Модель узнавания голоса не скачана: кнопка «Скачать», ход скачивания и ошибка.
import type { SpeakerModel } from '../../state/peopleActions'

type Props = { model: SpeakerModel; onDownload: () => void }

function percent(model: SpeakerModel): string {
  return model.total_bytes ? ` ${Math.floor((model.done_bytes * 100) / model.total_bytes)}%` : ''
}

export default function ModelBanner({ model, onDownload }: Props) {
  if (model.ready) return null
  return (
    <div className="people-banner" role="status">
      <span>
        {model.downloading
          ? `Скачиваю модель узнавания голоса…${percent(model)}`
          : `Чтобы узнавать людей по голосу, нужна модель (${model.size_mb} МБ, скачивается один раз, дальше работает без интернета).`}
      </span>
      {!model.downloading && (
        <button type="button" className="btn" onClick={onDownload}>
          Скачать модель
        </button>
      )}
      {model.error && !model.downloading && <span className="people-error">{model.error}</span>}
    </div>
  )
}
