// Модели в памяти Ollama с кнопкой «Выгрузить».
import { useState } from 'react'

type Props = {
  /** Имена из status.ollama.loaded; null — Ollama недоступна. */
  loaded: string[] | null
  onUnload: (name: string) => Promise<void>
}

export default function LoadedModels({ loaded, onUnload }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const unload = async (name: string) => {
    setBusy(name)
    try {
      await onUnload(name)
    } finally {
      setBusy(null)
    }
  }
  if (loaded === null) return <p className="core-note">Ollama недоступна</p>
  if (loaded.length === 0) return <p className="core-note">В памяти нет моделей</p>
  return (
    <ul className="core-models">
      {loaded.map((name) => (
        <li key={name}>
          <span className="core-model-name">{name}</span>
          <button type="button" className="btn small btn-plain" disabled={busy !== null} onClick={() => void unload(name)}>
            {busy === name ? 'Выгружается…' : 'Выгрузить'}
          </button>
        </li>
      ))}
    </ul>
  )
}
