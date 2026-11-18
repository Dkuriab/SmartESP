// Токен доступа к ядру: из адреса (?token=) или из localStorage.

const STORAGE_KEY = 'smartesp.token'

/** Читает токен из хранилища; любая ошибка доступа — как «нет токена». */
function loadSaved(storage: Storage | null): string | null {
  try {
    return storage?.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

/** Сохраняет токен; без хранилища интерфейс работает, токен не запоминается. */
export function saveToken(storage: Storage | null, token: string): void {
  try {
    storage?.setItem(STORAGE_KEY, token)
  } catch {
    // хранилище недоступно — не страшно
  }
}

/**
 * Достаёт токен: сначала из `?token=` в адресе, иначе из хранилища.
 * Токен из адреса сохраняется и убирается из адреса через replaceUrl
 * (остальные параметры и hash остаются).
 */
export function readToken(
  location: Location,
  storage: Storage | null,
  replaceUrl: (url: string) => void,
): string | null {
  const params = new URLSearchParams(location.search)
  const fromUrl = params.get('token')
  if (!fromUrl) return loadSaved(storage)
  saveToken(storage, fromUrl)
  params.delete('token')
  const rest = params.toString()
  replaceUrl(`${location.pathname}${rest ? `?${rest}` : ''}${location.hash}`)
  return fromUrl
}
