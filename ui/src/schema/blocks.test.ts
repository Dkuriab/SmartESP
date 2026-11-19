import { describe, expect, it } from 'vitest'
import { makeState } from '../components/fixtures'
import { listStages } from './blocks'

describe('listStages', () => {
  it('knows the clock stage: Russian title, disabled until configured', () => {
    const off = listStages(makeState()).find((s) => s.kind === 'clock')
    expect(off).toMatchObject({ title: 'Время', enabled: false })
    expect(off?.description).not.toBe('')
  })
})
