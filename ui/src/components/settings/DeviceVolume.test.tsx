import { fireEvent, render, screen } from '@testing-library/react'
import DeviceVolume from './DeviceVolume'

describe('DeviceVolume', () => {
  it('сохраняет новую громкость, когда отпустили ползунок; ту же — не шлёт', () => {
    const onSave = vi.fn()
    render(<DeviceVolume volume={50} disabled={false} onSave={onSave} />)
    const slider = screen.getByRole('slider', { name: 'Громкость' })
    fireEvent.pointerUp(slider)
    expect(onSave).not.toHaveBeenCalled()
    fireEvent.change(slider, { target: { value: '70' } })
    expect(screen.getByText('70 %')).toBeInTheDocument()
    fireEvent.pointerUp(slider)
    expect(onSave).toHaveBeenCalledWith(70)
  })
})
