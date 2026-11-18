// Хук состояния ядра: токен, загрузка ресурсов, живые события, действия.
import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import { createClient } from '../api/client'
import type { CoreEvent } from '../api/events'
import { connectEvents } from '../api/events'
import { readToken, saveToken } from '../api/token'
import type { CoreActions } from './actions'
import { createActions } from './actions'
import { AFTER_CHANGE, ALL_RESOURCES, createLoader } from './load'
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

/**
 * Пропускает действия, пока ворота открыты. Ответы на запросы старого клиента
 * (после смены токена) закрытыми воротами отбрасываются.
 */
function createGate(dispatch: Dispatch) {
  let open = true
  return {
    dispatch: ((action) => {
      if (open) dispatch(action)
    }) as Dispatch,
    open: () => {
      open = true
    },
    close: () => {
      open = false
    },
  }
}

/** Загружает ресурсы сразу и при каждом (пере)подключении событий; возвращает отключение. */
function connect(token: string, client: ReturnType<typeof createClient>, dispatch: Dispatch): () => void {
  const gate = createGate(dispatch)
  const live = gate.dispatch
  const load = createLoader(client, live)
  load(ALL_RESOURCES) // данные видны, даже если WebSocket не подключается
  const conn = connectEvents(token, {
    onOpen() {
      live({ type: 'opened' })
      load(ALL_RESOURCES)
    },
    onEvent(event: CoreEvent) {
      live({ type: 'event', event })
      if (REFRESH_ON.has(event.kind)) load(AFTER_CHANGE)
    },
    onClose(code) {
      live({ type: 'connection', connection: code === AUTH_FAILED ? 'unauthorized' : 'offline' })
    },
  })
  return () => {
    gate.close()
    conn.close()
  }
}

/**
 * Состояние ядра и действия. Ресурсы загружаются сразу и при каждом
 * (пере)подключении WebSocket; связь пропала — данные остаются последними известными.
 */
export function useCore(): [CoreState, CoreActions] {
  // объект, чтобы повторный ввод того же токена тоже переподключал
  const [token, setToken] = useState(() => ({ value: initialToken() }))
  const [state, dispatch] = useReducer(reduce, token.value, (t) =>
    initialState(t ? 'connecting' : 'unauthorized'),
  )
  // клиент и его ворота — на каждый токен: ответы старого клиента не меняют состояние
  const { client, gate } = useMemo(
    () => ({ client: createClient(token.value ?? ''), gate: createGate(dispatch) }),
    [token],
  )
  const onToken = useCallback((value: string) => {
    saveToken(storage(), value)
    dispatch({ type: 'connection', connection: 'connecting' })
    setToken({ value })
  }, [])
  useEffect(() => {
    gate.open() // повторный запуск эффекта (StrictMode) открывает снова
    return gate.close
  }, [gate])
  const config = state.config
  // действия пересоздаются при новых настройках: setDispatcher правит текущие executors
  const actions = useMemo(
    () => createActions({ client, dispatch: gate.dispatch, getConfig: () => config, onToken }),
    [client, gate, config, onToken],
  )
  useEffect(() => {
    if (!token.value) return
    return connect(token.value, client, dispatch)
  }, [client, token])
  return [state, actions]
}
