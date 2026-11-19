import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeActions, makeState } from '../fixtures'
import SchemaView from './SchemaView'

describe('SchemaView', () => {
  it('renders device cards', () => {
    render(<div style={{ width: 800, height: 600 }}><SchemaView state={makeState()} actions={makeActions()} /></div>)
    expect(screen.getByText('Кухня')).toBeInTheDocument()
    expect(screen.getByText('Спальня')).toBeInTheDocument()
  })

  it('click on a device selects it', () => {
    const actions = makeActions()
    render(<div style={{ width: 800, height: 600 }}><SchemaView state={makeState()} actions={actions} /></div>)
    fireEvent.click(screen.getByText('Кухня'))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'device', id: 'a' })
  })
})
