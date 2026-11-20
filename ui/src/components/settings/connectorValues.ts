// Значения формы настроек коннектора: разбор списка папок, проверки до отправки, что изменилось.
import type { ConnectorSetting } from '../../state/model'

/** Папка в списке «имя=путь;имя=путь». */
export type FolderRow = { name: string; path: string }

/** Как ядро: длиннее не принимает. */
export const MAX_VALUE = 500

/** «имя=путь;…» → строки списка; пустые записи пропускаются. */
export function parseFolders(value: string): FolderRow[] {
  return value
    .split(';')
    .filter((item) => item.trim() !== '')
    .map((item) => {
      const at = item.indexOf('=')
      if (at < 0) return { name: '', path: item.trim() }
      return { name: item.slice(0, at).trim(), path: item.slice(at + 1).trim() }
    })
}

/** Строки списка → «имя=путь;…»; совсем пустые строки не пишутся. */
export function formatFolders(rows: FolderRow[]): string {
  return rows
    .map((r) => ({ name: r.name.trim(), path: r.path.trim() }))
    .filter((r) => r.name !== '' || r.path !== '')
    .map((r) => `${r.name}=${r.path}`)
    .join(';')
}

const absolute = (path: string) => path.startsWith('/') || path === '~' || path.startsWith('~/')

function folderError(rows: FolderRow[]): string {
  const names = new Set<string>()
  for (const { name, path } of rows) {
    if (!name || !path) return 'У каждой папки нужны имя и путь'
    if (/[=;]/.test(name)) return `Имя «${name}»: без «=» и «;»`
    if (path.includes(';')) return `Путь «${path}»: без «;»`
    if (!absolute(path)) return `Путь «${path}» должен начинаться с / или ~/`
    const key = name.toLocaleLowerCase('ru')
    if (names.has(key)) return `Имя «${name}» повторяется`
    names.add(key)
  }
  return ''
}

/** Текст ошибки значения ('' — годится); существование папок проверит ядро. */
export function valueError(setting: ConnectorSetting, value: string): string {
  if (value.length > MAX_VALUE) return `Не длиннее ${MAX_VALUE} символов`
  if (/[\0\r\n]/.test(value)) return 'Значение в одну строку'
  if (setting.type === 'path' && value !== '' && !absolute(value)) return 'Путь должен начинаться с / или ~/'
  if (setting.type === 'list') return folderError(parseFolders(value))
  return ''
}

/** Начальное значение поля: секрет — пустое поле (ввод нового), список — как есть. */
export function initialValue(setting: ConnectorSetting): string {
  return setting.type === 'secret' ? '' : (setting.value ?? '')
}

/** Значение из ядра в той форме, в какой его соберёт форма (список — заново записанный). */
function baseline(setting: ConnectorSetting): string {
  const value = setting.value ?? ''
  return setting.type === 'list' ? formatFolders(parseFolders(value)) : value
}

/**
 * Только изменённые значения. Секрет — пустое поле значит «не менять» (маска «•••» назад не
 * уходит, стереть секрет можно только в config.yaml); список сравнивается в записанной форме.
 */
export function changedEnv(settings: ConnectorSetting[], values: Record<string, string>): Record<string, string> {
  const env: Record<string, string> = {}
  for (const s of settings) {
    const value = values[s.key] ?? ''
    const changed = s.type === 'secret' ? value !== '' : value !== baseline(s)
    if (changed) env[s.key] = value
  }
  return env
}
