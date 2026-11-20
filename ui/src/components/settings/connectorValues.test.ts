import { describe, expect, it } from 'vitest'
import type { ConnectorSetting } from '../../state/model'
import { changedEnv, formatFolders, parseFolders, valueError } from './connectorValues'

const setting = (type: ConnectorSetting['type'], value = ''): ConnectorSetting => ({
  key: 'K',
  title: 'Поле',
  type,
  hint: '',
  value,
})

describe('список папок', () => {
  it('разбор и запись туда и обратно', () => {
    const rows = parseFolders(' песочница = /tmp/s ;; работа=~/w;')
    expect(rows).toEqual([
      { name: 'песочница', path: '/tmp/s' },
      { name: 'работа', path: '~/w' },
    ])
    expect(formatFolders([...rows, { name: ' ', path: '' }])).toBe('песочница=/tmp/s;работа=~/w')
  })

  it('запись без «=» — путь без имени', () => {
    expect(parseFolders('/tmp/s')).toEqual([{ name: '', path: '/tmp/s' }])
  })
})

describe('valueError', () => {
  it.each([
    ['path', '', ''],
    ['path', '/Users/me', ''],
    ['path', '~/x', ''],
    ['path', 'relative', 'Путь должен начинаться с / или ~/'],
    ['text', 'a\nb', 'Значение в одну строку'],
    ['text', 'x'.repeat(501), 'Не длиннее 500 символов'],
    ['list', 'a=/x;b=~/y', ''],
    ['list', 'a=', 'У каждой папки нужны имя и путь'],
    ['list', '=/x', 'У каждой папки нужны имя и путь'],
    ['list', 'a=x', 'Путь «x» должен начинаться с / или ~/'],
    ['list', 'Дом=/x;дом=/y', 'Имя «дом» повторяется'],
  ] as const)('%s «%s» → «%s»', (type, value, error) => {
    expect(valueError(setting(type), value)).toBe(error)
  })
})

describe('changedEnv', () => {
  it('только изменённое; секрет с маской не уходит', () => {
    const settings = [
      { ...setting('text', 'Тверь'), key: 'CITY' },
      { ...setting('secret', '•••'), key: 'TOKEN' },
      { ...setting('flag', ''), key: 'ON' },
    ]
    expect(changedEnv(settings, { CITY: 'Тверь', TOKEN: '•••', ON: '1' })).toEqual({ ON: '1' })
    expect(changedEnv(settings, { CITY: 'Москва', TOKEN: 'new', ON: '' })).toEqual({ CITY: 'Москва', TOKEN: 'new' })
  })
})
