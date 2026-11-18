import { describe, expect, it, vi } from 'vitest'
import { readToken } from './token'

function fakeStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    data,
    getItem: (k: string) => data[k] ?? null,
    setItem: (k: string, v: string) => {
      data[k] = v
    },
  } as unknown as Storage & { data: Record<string, string> }
}

function loc(search: string, hash = '') {
  return { pathname: '/ui', search, hash } as Location
}

describe('readToken', () => {
  it('берёт токен из адреса, сохраняет и убирает из адреса', () => {
    const storage = fakeStorage()
    const replaceUrl = vi.fn()
    const token = readToken(loc('?token=abc&x=1', '#h'), storage, replaceUrl)
    expect(token).toBe('abc')
    expect(storage.data['smartesp.token']).toBe('abc')
    expect(replaceUrl).toHaveBeenCalledWith('/ui?x=1#h')
  })

  it('убирает ?, если других параметров нет', () => {
    const replaceUrl = vi.fn()
    readToken(loc('?token=abc'), fakeStorage(), replaceUrl)
    expect(replaceUrl).toHaveBeenCalledWith('/ui')
  })

  it('без токена в адресе берёт из хранилища', () => {
    const replaceUrl = vi.fn()
    const storage = fakeStorage({ 'smartesp.token': 'saved' })
    expect(readToken(loc(''), storage, replaceUrl)).toBe('saved')
    expect(replaceUrl).not.toHaveBeenCalled()
  })

  it('возвращает null, если токена нет нигде', () => {
    expect(readToken(loc(''), fakeStorage(), vi.fn())).toBeNull()
    expect(readToken(loc(''), null, vi.fn())).toBeNull()
  })

  it('не падает, если хранилище бросает исключение', () => {
    const storage = {
      getItem: () => {
        throw new Error('denied')
      },
      setItem: () => {
        throw new Error('denied')
      },
    } as unknown as Storage
    const replaceUrl = vi.fn()
    expect(readToken(loc('?token=abc'), storage, replaceUrl)).toBe('abc')
    expect(replaceUrl).toHaveBeenCalled()
    expect(readToken(loc(''), storage, replaceUrl)).toBeNull()
  })
})
