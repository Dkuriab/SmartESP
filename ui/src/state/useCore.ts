// Хук состояния ядра: токен, загрузка ресурсов, живые события, действия.
import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import { createClient } from '../api/client'
import type { CoreEvent } from '../api/events'
import { connectEvents } from '../api/events'
import { readToken, saveToken } from '../api/token'
import type { CoreActions } from './actions'
import { createActions } from './actions'
import { createCoreActions } from './coreActions'
import type { Loader } from './load'
import { AFTER_CHANGE, ALL_RESOURCES, createLoader } from './load'
import type { CoreState } from './model'
import { initialState } from './model'
import { reduce } from './reducer'
import type { Dispatch } from './request'
import { createSentExecutors } from './sentExecutors'

/** Ядро закрывает WebSocket с этим кодом при неверном токене. */
const AUTH_FAILED = 4401
/** После этих событий заново читаем config, status, voices. */
const REFRESH_ON = new Set(['change_applied', 'voice_ready', 'core_state'])
/**
 * Пока связь есть, status перечитывается так часто: модели в памяти Ollama, коннекторы
 * и applying приходят без событий.
 */
const STATUS_POLL_MS = 5_000

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

/** Пропускает действия дальше; Ollama снова стала доступна — перечитывает модели. */
function watchOllama(dispatch: Dispatch, reloadModels: () => void): Dispatch {
  let reachable: boolean | null = null
  return (action) => {
    dispatch(action)
    if (action.type !== 'loaded' || action.resource !== 'status') return
    const now: unknown = action.data.ollama?.reachable
    if (typeof now !== 'boolean') return
    if (reachable === false && now) reloadModels()
    reachable = now
  }
}

/**
 * Перечитывание status по таймеру, пока связь есть и страница видна (скрытая вкладка
 * не шумит журналом ядра). Запросы не копятся: загрузчик не начинает второй, пока идёт первый.
 */
function statusPoll(load: Loader) {
  let timer: ReturnType<typeof setInterval> | undefined
  const stop = () => clearInterval(timer)
  const start = () => {
    stop()
    timer = setInterval(() => {
      if (!document.hidden) load(['status'])
    }, STATUS_POLL_MS)
  }
  return { start, stop }
}

/** Загружает ресурсы сразу и при каждом (пере)подключении событий; возвращает отключение. */
function connect(token: string, client: ReturnType<typeof createClient>, dispatch: Dispatch): () => void {
  const gate = createGate(dispatch)
  const live = gate.dispatch
  const load: Loader = createLoader(client, watchOllama(live, () => load(['models'])))
  const poll = statusPoll(load)
  load(ALL_RESOURCES) // данные видны, даже если WebSocket не подключается
  const conn = connectEvents(token, {
    onOpen() {
      live({ type: 'opened' })
      load(ALL_RESOURCES)
      poll.start()
    },
    onEvent(event: CoreEvent) {
      live({ type: 'event', event })
      if (REFRESH_ON.has(event.kind)) load(AFTER_CHANGE)
    },
    onClose(code) {
      poll.stop()
      live({ type: 'connection', connection: code === AUTH_FAILED ? 'unauthorized' : 'offline' })
    },
  })
  return () => {
    poll.stop()
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
  // клиент и его ворота — на каждый токен: ответы старого клиента не меняют состояние;
  // отправленные исполнители переживают пересоздание действий
  const { client, gate, sent, coreTab } = useMemo(() => {
    const client = createClient(token.value ?? '')
    const gate = createGate(dispatch)
    // действия вкладки «Ядро» — на токен: подписка на журнал не зависит от настроек
    return { client, gate, sent: createSentExecutors(), coreTab: createCoreActions(client, gate.dispatch, token.value ?? '') }
  }, [token])
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
  // действия пересоздаются при новых настройках: правки исполнителей строятся на текущих executors
  const actions = useMemo(
    () =>
      createActions({
        client,
        dispatch: gate.dispatch,
        getConfig: () => config,
        onToken,
        sentExecutors: sent,
        token: token.value ?? '',
        coreTab,
      }),
    [client, gate, config, onToken, sent, token, coreTab],
  )
  useEffect(() => {
    if (!token.value) return
    // события и загрузки видит и память отправленных исполнителей
    const observed: Dispatch = (action) => {
      sent.observe(action)
      dispatch(action)
    }
    return connect(token.value, client, observed)
  }, [client, token, sent])
  return [state, actions]
}
