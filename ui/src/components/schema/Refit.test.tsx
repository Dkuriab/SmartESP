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

  it('новый набор узлов — схема подгоняется заново', () => {
    const view = render(<Refit fitKey="3" width={800} height={600} />)
    vi.runAllTimers()
    fitView.mockClear()
    view.rerender(<Refit fitKey="3" width={800} height={600} />)
    vi.runAllTimers()
    expect(fitView).not.toHaveBeenCalled()
    view.rerender(<Refit fitKey="4" width={800} height={600} />)
    expect(fitView).toHaveBeenCalledTimes(1)
    // на широком экране не раздувает, на узком не мельчит
    expect(fitView).toHaveBeenCalledWith(expect.objectContaining({ maxZoom: 1.2, minZoom: 0.45 }))
  })

  it('изменение размера области — одна подгонка после паузы', () => {
    const view = render(<Refit fitKey="3" width={800} height={600} />)
    vi.runAllTimers()
    fitView.mockClear()
    for (let w = 801; w < 806; w++) view.rerender(<Refit fitKey="3" width={w} height={600} />)
    vi.advanceTimersByTime(100)
    expect(fitView).not.toHaveBeenCalled()
    vi.advanceTimersByTime(100)
    expect(fitView).toHaveBeenCalledTimes(1)
    view.rerender(<Refit fitKey="3" width={900} height={600} />)
    view.unmount()
    vi.advanceTimersByTime(1000)
    expect(fitView).toHaveBeenCalledTimes(1)
  })

  it('регрессия «схема пропадает»: при нулевом размере не подгоняет, подгоняет, когда место появилось', () => {
    const view = render(<Refit fitKey="3" width={0} height={0} />)
    view.rerender(<Refit fitKey="4" width={800} height={0} />)
    vi.runAllTimers()
    expect(fitView).not.toHaveBeenCalled()
    view.rerender(<Refit fitKey="4" width={800} height={600} />)
    expect(fitView).toHaveBeenCalledTimes(1)
  })
})
