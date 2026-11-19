// «Доступ из сети»: адреса ядра для телефона или другого компьютера.
import { useEffect, useEffectEvent, useState } from 'react'

type Props = {
  /** Адреса из GET /access; ошибка — пустой список. */
  loadAccess: () => Promise<string[]>
  /** Связь с ядром есть: адреса перечитываются при каждом подключении. */
  online: boolean
}

const COPIED_MS = 2000

/** Копирует в буфер; в http-странице из сети буфера нет — тогда false. */
async function copy(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export default function AccessInfo({ loadAccess, online }: Props) {
  const [urls, setUrls] = useState<string[] | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const load = useEffectEvent(() => loadAccess())
  useEffect(() => {
    if (!online) return
    let live = true
    void load().then((list) => live && setUrls(list))
    return () => {
      live = false
    }
  }, [online])
  // «Скопировано» держится COPIED_MS, затем кнопка снова «Скопировать»
  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(null), COPIED_MS)
    return () => clearTimeout(timer)
  }, [copied])
  const onCopy = async (url: string) => {
    if (await copy(url)) setCopied(url)
  }
  return (
    <section className="access" aria-label="Доступ из сети">
      <div className="cap">Доступ из сети</div>
      {urls?.length === 0 && <p className="access-none">Адрес в сети не найден</p>}
      {urls?.map((url) => (
        <div key={url} className="access-row">
          <span className="access-url" title={url}>{url}</span>
          <button type="button" className="chip" onClick={() => void onCopy(url)}>
            {copied === url ? 'Скопировано' : 'Скопировать'}
          </button>
        </div>
      ))}
    </section>
  )
}
