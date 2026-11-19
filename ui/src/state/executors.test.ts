import { describe, expect, it, vi } from 'vitest'
import { listExecutors } from '../schema/blocks'
import { makeConfig, makeState } from '../components/fixtures'
import type { Client } from './actions'
import { createActions } from './actions'
import { VOICE_PROMPT } from './executors'
import type { Action, Config } from './model'

function cfg(executors: unknown[]): Config {
  return makeConfig({ executors })
}

const entry = { id: 'dispatcher', name: 'Диспетчер', entry: true, model: 'qwen3', delegates: [{ to: 'big', when: 'сложное' }] }
const big = { id: 'big', name: 'Большая', entry: false, model: 'r1', description: '', delegates: [] }

function setup(current: Config) {
  const client = { PATCH: vi.fn().mockResolvedValue({ data: { change_id: 1, status: 'accepted', error: '' }, response: { status: 200 } }) }
  const dispatched: Action[] = []
  const actions = createActions({
    client: client as unknown as Client,
    dispatch: (a) => dispatched.push(a),
    getConfig: () => current,
    onToken: vi.fn(),
  })
  const sent = () => (client.PATCH.mock.calls.at(-1)?.[1] as { body: { executors: Record<string, unknown>[] } }).body.executors
  return { client, actions, sent }
}

describe('listExecutors', () => {
  it('входной первым, ссылки из настроек', () => {
    const items = listExecutors(makeState({ config: cfg([big, entry]) }))
    expect(items.map((e) => e.id)).toEqual(['dispatcher', 'big'])
    expect(items[0]?.links).toEqual([{ to: 'big', when: 'сложное', active: true }])
    expect(items[0]?.systemPrompt).toBe('')
  })

  it('active: по when или по описанию цели', () => {
    const a = { ...entry, delegates: [{ to: 'big', when: '  ' }] }
    expect(listExecutors(makeState({ config: cfg([a, big]) }))[0]?.links[0]?.active).toBe(false)
    const described = { ...big, description: 'расчёты' }
    expect(listExecutors(makeState({ config: cfg([a, described]) }))[0]?.links[0]?.active).toBe(true)
  })

  it('без настроек пусто', () => {
    expect(listExecutors(makeState())).toEqual([])
  })
})

describe('executor actions', () => {
  it('addExecutor даёт executor-1, затем executor-2; PATCH — весь список', async () => {
    const first = setup(cfg([entry, big]))
    await first.actions.addExecutor()
    const list = first.sent()
    expect(list.map((e) => e.id)).toEqual(['dispatcher', 'big', 'executor-1'])
    expect(list[2]).toMatchObject({ name: 'Исполнитель 1', model: 'qwen3', entry: false })
    expect(list[2]?.system_prompt).toBe(VOICE_PROMPT)
    // тот же текст, что BIG_SYSTEM_PROMPT в настройках ядра по умолчанию
    expect(VOICE_PROMPT).toBe('Ты отвечаешь голосом через колонку: по-русски, без разметки и списков, связно, до 6–8 предложений.')
    const second = setup(cfg(list))
    await second.actions.addExecutor()
    expect(second.sent().map((e) => e.id)).toContain('executor-2')
  })

  it('removeExecutor убирает исполнителя и ссылки на него', async () => {
    const { actions, sent } = setup(cfg([entry, big]))
    await actions.removeExecutor('big')
    expect(sent()).toEqual([{ ...entry, delegates: [] }])
  })

  it('входного и неизвестного не удаляет: ни PATCH, ни «применяется»', async () => {
    const { actions, client } = setup(cfg([entry, big]))
    await actions.removeExecutor('dispatcher')
    await actions.removeExecutor('nobody')
    expect(client.PATCH).not.toHaveBeenCalled()
  })

  it('setLink на себя и на неизвестного — ничего не шлёт', async () => {
    const { actions, client } = setup(cfg([entry, big]))
    await actions.setLink('dispatcher', 'dispatcher', true, 'x')
    await actions.setLink('dispatcher', 'nobody', true, 'x')
    await actions.setLink('nobody', 'big', true, 'x')
    expect(client.PATCH).not.toHaveBeenCalled()
  })

  it('addExecutor отдаёт id нового исполнителя; без настроек — null', async () => {
    const { actions } = setup(cfg([entry, big]))
    expect(await actions.addExecutor()).toBe('executor-1')
    const none = setup(makeConfig({ executors: [] }))
    expect(await none.actions.addExecutor()).toBeNull()
  })

  it('setLink включает, меняет when и выключает', async () => {
    const on = setup(cfg([{ ...entry, delegates: [] }, big]))
    await on.actions.setLink('dispatcher', 'big', true, 'код')
    expect(on.sent()[0]?.delegates).toEqual([{ to: 'big', when: 'код' }])
    const change = setup(cfg([entry, big]))
    await change.actions.setLink('dispatcher', 'big', true, 'новое')
    expect(change.sent()[0]?.delegates).toEqual([{ to: 'big', when: 'новое' }])
    const off = setup(cfg([entry, big]))
    await off.actions.setLink('dispatcher', 'big', false, '')
    expect(off.sent()[0]?.delegates).toEqual([])
  })

  it('updateExecutor правит поля без undefined', async () => {
    const { actions, sent } = setup(cfg([entry, big]))
    await actions.updateExecutor('big', { systemPrompt: 'пром', name: undefined })
    expect(sent()[1]).toMatchObject({ name: 'Большая', system_prompt: 'пром' })
  })
})
