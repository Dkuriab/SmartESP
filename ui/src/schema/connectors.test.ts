import { describe, expect, it } from 'vitest'
import { makeConfig, makeState, makeStatus } from '../components/fixtures'
import { HIDDEN, connectorToggle, listConnectors, modelInMemory, shownValue } from './connectors'

const configured = [
  { id: 'calc', name: 'Калькулятор', command: 'uv', args: [], env: {}, enabled: true },
  { id: 'weather', name: 'Погода', command: 'uv', env: { WEATHER_PLACE: 'Москва', API_KEY: 'abc' }, enabled: true },
  { id: 'claude_tasks', name: 'Задачи Клоду', command: 'uv', env: { CLAUDE_TASK_FOLDERS: '' }, enabled: false },
]

function state() {
  return makeState({
    config: makeConfig({ connectors: configured }),
    status: makeStatus({
      connectors: [
        { id: 'calc', name: 'Калькулятор', state: 'ready', tools: ['calc_add'], error: '', kind: 'mcp' as const },
        { id: 'weather', name: 'Погода', state: 'failed', tools: [], error: 'упал', kind: 'mcp' as const },
        { id: 'extra', name: 'Чужой', state: 'starting', tools: [], error: '', kind: 'mcp' as const },
      ],
    }),
  })
}

describe('listConnectors', () => {
  it('сводит настройки и status, порядок — как в настройках', () => {
    const list = listConnectors(state())
    expect(list.map((c) => [c.id, c.state, c.enabled])).toEqual([
      ['calc', 'ready', true],
      ['weather', 'failed', true],
      ['claude_tasks', 'disabled', false],
      ['extra', 'starting', true],
    ])
    expect(list[0]?.tools).toEqual(['calc_add'])
    expect(list[1]?.error).toBe('упал')
  })

  it('скрывает значения секретов в окружении', () => {
    const weather = listConnectors(state())[1]
    expect(weather?.env).toEqual([
      { key: 'WEATHER_PLACE', value: 'Москва' },
      { key: 'API_KEY', value: HIDDEN },
    ])
    expect(shownValue('BOT_TOKEN', '')).toBe('')
    expect(shownValue('my_secret', 'x')).toBe(HIDDEN)
  })
})

describe('connectorToggle', () => {
  it('шлёт только id и enabled: ядро сливает по id', () => {
    expect(connectorToggle('claude_tasks', true)).toEqual([{ id: 'claude_tasks', enabled: true }])
  })
})

describe('modelInMemory', () => {
  it('сравнивает имена с учётом тега latest', () => {
    const s = makeState({ status: makeStatus({ ollama: { reachable: true, loaded: ['qwen3:latest', 'gemma:4b'] } }) })
    expect(modelInMemory(s, 'qwen3')).toBe(true)
    expect(modelInMemory(s, 'gemma:4b')).toBe(true)
    expect(modelInMemory(s, 'gemma')).toBe(false)
    expect(modelInMemory(s, '')).toBe(false)
  })
})
