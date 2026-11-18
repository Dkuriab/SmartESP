// Хук состояния ядра: токен, загрузка ресурсов, живые события, действия.
import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import { createClient } from '../api/client'
import type { CoreEvent } from '../api/events'
import { connectEvents } from '../api/events'
import { readToken, saveToken } from '../api/token'
import type { CoreActions } from './actions'
import { createActions } from './actions'
import { AFTER_CHANGE, ALL_RESOURCES, loadResources } from './load'
import type { CoreState } from './model'
import { initialState } from './model'
import { reduce } from './reducer'
import type { Dispatch } from './request'

/** Ядро закрывает WebSocket с этим кодом при неверном токене. */
const AUTH_FAILED = 4401
/** После этих событий заново читаем config, status, voices. */
const REFRESH_ON = new Set(['change_applied', 'voice_ready'])

function storage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function initialToken(): string | null {
  return readToken(window.location, storage(), (url) => window.history.replaceState(null, '', url))
}

/** Подключает события и загрузку; возвращает функцию отключения. */
function connect(token: string, client: ReturnType<typeof createClient>, dispatch: Dispatch): () => void {
  let alive = true
  const live: Dispatch = (action) => {
    if (alive) dispatch(action)
  }
  const conn = connectEvents(token, {
    onOpen() {
      live({ type: 'connection', connection: 'online' })
      void loadResources(client, live, ALL_RESOURCES)
    },
    onEvent(event: CoreEvent) {
      live({ type: 'event', event })
      if (REFRESH_ON.has(event.kind)) void loadResources(client, live, AFTER_CHANGE)
    },
    onClose(code) {
      live({ type: 'connection', connection: code === AUTH_FAILED ? 'unauthorized' : 'offline' })
    },
  })
  return () => {
    alive = false
    conn.close()
  }
}

/**
 * Состояние ядра и действия. Ресурсы загружаются при каждом (пере)подключении
 * WebSocket; связь пропала — данные остаются последними известными.
 */
export function useCore(): [CoreState, CoreActions] {
  // объект, чтобы повторный ввод того же токена тоже переподключал
  const [token, setToken] = useState(() => ({ value: initialToken() }))
  const [state, dispatch] = useReducer(reduce, token.value, (t) =>
    initialState(t ? 'connecting' : 'unauthorized'),
  )
  const client = useMemo(() => createClient(token.value ?? ''), [token])
  const onToken = useCallback((value: string) => {
    saveToken(storage(), value)
    dispatch({ type: 'connection', connection: 'connecting' })
    setToken({ value })
  }, [])
  const config = state.config
  // действия пересоздаются при новых настройках: setDispatcher правит текущие executors
  const actions = useMemo(
    () => createActions({ client, dispatch, getConfig: () => config, onToken }),
    [client, config, onToken],
  )
  useEffect(() => {
    if (!token.value) return
    return connect(token.value, client, dispatch)
  }, [client, token])
  return [state, actions]
}
