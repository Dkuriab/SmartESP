import { act, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useBoxSize } from './useBoxSize'

function Probe() {
  const [box, setBox] = useState<HTMLDivElement | null>(null)
  const { width, height } = useBoxSize(box)
  return <div ref={setBox}>{`${width}×${height}`}</div>
}

describe('useBoxSize без ResizeObserver', () => {
  const real = globalThis.ResizeObserver
  afterEach(() => {
    globalThis.ResizeObserver = real
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('размер берётся из getBoundingClientRect при монтировании и при изменении окна', () => {
    vi.useFakeTimers()
    // @ts-expect-error — старый движок без ResizeObserver
    delete globalThis.ResizeObserver
    let rect = { width: 640, height: 480 }
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => rect as DOMRect)
    render(<Probe />)
    act(() => void vi.runAllTimers())
    expect(screen.getByText('640×480')).toBeInTheDocument()
    rect = { width: 900, height: 500 }
    act(() => {
      window.dispatchEvent(new Event('resize'))
      vi.runAllTimers()
    })
    expect(screen.getByText('900×500')).toBeInTheDocument()
  })
})
