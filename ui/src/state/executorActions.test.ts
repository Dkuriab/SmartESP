import { describe, expect, it, vi } from 'vitest'
import { makeConfig } from '../components/fixtures'
import type { Client } from './actions'
import { createActions } from './actions'
import type { Config } from './model'
import { createSentExecutors } from './sentExecutors'

const entry = { id: 'dispatcher', name: 'Диспетчер', entry: true, model: 'qwen3', delegates: [] }
const big = { id: 'big', name: 'Большая', entry: false, model: 'r1', description: '', delegates: [] }
const config: Config = makeConfig({ executors: [entry, big] })

type Reply = { data?: unknown; error?: unknown; response: { status: number } }
const accepted = (id: number): Reply => ({ data: { change_id: id, status: 'accepted', error: '' }, response: { status: 200 } })
const invalid: Reply = { error: { error: 'нельзя' }, response: { status: 422 } }

/** PATCH, ответ на который приходит, когда тест его отпустит. */
function heldPatch() {
  const releases: Array<(r: Reply) => void> = []
  const PATCH = vi.fn(() => new Promise<Reply>((resolve) => releases.push(resolve)))
  const body = (i: number) => (PATCH.mock.calls[i] as unknown[] | undefined)?.[1] as { body: { executors: Record<string, unknown>[] } }
  return { PATCH, releases, body }
}

function setup(clock = { t: 100 }) {
  const held = heldPatch()
  const sent = createSentExecutors(() => clock.t)
  const actions = createActions({
    client: { PATCH: held.PATCH } as unknown as Client,
    dispatch: vi.fn(),
    getConfig: () => config,
    onToken: vi.fn(),
    token: 't',
    sentExecutors: sent,
  })
  return { ...held, actions, sent, clock }
}

const appliedEvent = (id: number, ok = true) =>
  ({ type: 'event', event: { kind: 'change_applied', data: { change_id: id, ok, error: ok ? '' : 'сбой' }, at: 0 } }) as const
const configLoaded = (requestedAt: number) => ({ type: 'loaded', resource: 'config', data: config, requestedAt }) as const

describe('правки исполнителей подряд', () => {
  it('вторая правка, пока первый PATCH без ответа, строится на первой', async () => {
    const { actions, PATCH, releases, body } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    const second = actions.setLink('dispatcher', 'big', true, 'код')
    expect(PATCH).toHaveBeenCalledTimes(2)
    expect(body(1).body.executors[1]).toMatchObject({ name: 'Умная' })
    expect(body(1).body.executors[0]?.delegates).toEqual([{ to: 'big', when: 'код' }])
    releases.forEach((r, i) => r(accepted(i + 1)))
    await Promise.all([first, second])
  })

  it('PATCH отклонён — следующая правка снова от настроек', async () => {
    const { actions, releases, body, sent } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    releases[0]?.(invalid)
    await first
    expect(sent.base()).toBeNull()
    void actions.setLink('dispatcher', 'big', true, 'код')
    expect(body(1).body.executors[1]).toMatchObject({ name: 'Большая' })
  })

  it('отправленное забывается, когда пришли настройки, запрошенные после применения', async () => {
    const { actions, releases, sent, clock } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    releases[0]?.(accepted(7))
    await first
    sent.observe(configLoaded(90)) // запрошены до применения — старые
    expect(sent.base()).not.toBeNull()
    clock.t = 200
    sent.observe(appliedEvent(7))
    sent.observe(configLoaded(150)) // запрос ушёл раньше применения
    expect(sent.base()).not.toBeNull()
    sent.observe(configLoaded(200))
    expect(sent.base()).toBeNull()
  })

  it('событие о применении раньше ответа PATCH тоже учитывается', async () => {
    const { actions, releases, sent } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    sent.observe(appliedEvent(7))
    releases[0]?.(accepted(7))
    await first
    sent.observe(configLoaded(100))
    expect(sent.base()).toBeNull()
  })

  it('ждёт применения последней из правок', async () => {
    const { actions, releases, sent } = setup()
    const a = actions.updateExecutor('big', { name: 'А' })
    const b = actions.updateExecutor('big', { name: 'Б' })
    releases[0]?.(accepted(1))
    releases[1]?.(accepted(2))
    await Promise.all([a, b])
    sent.observe(appliedEvent(1))
    sent.observe(configLoaded(500))
    expect(sent.base()?.[1]).toMatchObject({ name: 'Б' })
    sent.observe(appliedEvent(2))
    sent.observe(configLoaded(500))
    expect(sent.base()).toBeNull()
  })

  it('применена первая, пока вторая без ответа: перечитывание не теряет вторую', async () => {
    const { actions, releases, body, sent, clock } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    releases[0]?.(accepted(1))
    await first
    const second = actions.setLink('dispatcher', 'big', true, 'код') // PATCH без ответа
    clock.t = 200
    sent.observe(appliedEvent(1))
    sent.observe(configLoaded(200)) // настройки только с первой правкой
    releases[1]?.(accepted(2))
    await second
    void actions.updateExecutor('big', { description: 'всё' })
    expect(body(2).body.executors[0]?.delegates).toEqual([{ to: 'big', when: 'код' }])
    expect(body(2).body.executors[1]).toMatchObject({ name: 'Умная', description: 'всё' })
    sent.observe(appliedEvent(2))
    sent.observe(configLoaded(200))
    expect(sent.base()).not.toBeNull() // третья ещё не принята
  })

  it('отклонена вторая, первая принята и не применена: база — список первой', async () => {
    const { actions, releases, body, sent } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    releases[0]?.(accepted(1))
    await first
    const second = actions.setLink('dispatcher', 'big', true, 'код')
    releases[1]?.(invalid)
    await second
    expect(sent.base()?.[1]).toMatchObject({ name: 'Умная' })
    void actions.updateExecutor('big', { description: 'всё' })
    expect(body(2).body.executors[0]?.delegates).toEqual([])
    expect(body(2).body.executors[1]).toMatchObject({ name: 'Умная', description: 'всё' })
  })

  it('отклонена вторая, а первая уже применена и перечитана — база снова из настроек', async () => {
    const { actions, releases, sent, clock } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    releases[0]?.(accepted(1))
    await first
    const second = actions.setLink('dispatcher', 'big', true, 'код')
    clock.t = 200
    sent.observe(appliedEvent(1))
    sent.observe(configLoaded(200))
    expect(sent.base()).not.toBeNull() // вторая ещё без ответа
    releases[1]?.(invalid)
    await second
    expect(sent.base()).toBeNull()
  })

  it('отклонена вторая, пока первая без ответа: база — список первой', async () => {
    const { actions, releases, sent } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    const second = actions.setLink('dispatcher', 'big', true, 'код')
    releases[1]?.(invalid)
    await second
    expect(sent.base()?.[0]?.delegates).toEqual([])
    expect(sent.base()?.[1]).toMatchObject({ name: 'Умная' })
    releases[0]?.(accepted(1))
    await first
    expect(sent.base()?.[1]).toMatchObject({ name: 'Умная' })
  })

  it('ошибка применения или переподключение — забывается сразу', async () => {
    const { actions, releases, sent } = setup()
    const first = actions.updateExecutor('big', { name: 'Умная' })
    releases[0]?.(accepted(3))
    await first
    sent.observe(appliedEvent(3, false))
    expect(sent.base()).toBeNull()
    const again = actions.updateExecutor('big', { name: 'Снова' })
    releases[1]?.(accepted(4))
    await again
    sent.observe({ type: 'opened' })
    expect(sent.base()).toBeNull()
  })
})
