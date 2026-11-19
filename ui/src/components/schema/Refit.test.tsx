import { render } from '@testing-library/react'
import Refit from './Refit'

const fitView = vi.fn()
vi.mock('@xyflow/react', () => ({ useReactFlow: () => ({ fitView }) }))

describe('Refit', () => {
  beforeEach(() => {
    fitView.mockReset()
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('новое число узлов — схема подгоняется заново', () => {
    const view = render(<Refit count={3} />)
    fitView.mockClear()
    view.rerender(<Refit count={3} />)
    expect(fitView).not.toHaveBeenCalled()
    view.rerender(<Refit count={4} />)
    expect(fitView).toHaveBeenCalledTimes(1)
  })

  it('изменение размера окна — одна подгонка после паузы', () => {
    const view = render(<Refit count={3} />)
    fitView.mockClear()
    for (let i = 0; i < 5; i++) window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(100)
    expect(fitView).not.toHaveBeenCalled()
    vi.advanceTimersByTime(100)
    expect(fitView).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new Event('resize'))
    view.unmount()
    vi.advanceTimersByTime(1000)
    expect(fitView).toHaveBeenCalledTimes(1)
  })
})
