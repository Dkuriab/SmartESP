import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import { EdgeLabel } from './LinkEdge'
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

  it('executor whose model did not warm up says «модель недоступна»', () => {
    const status = makeStatus({ executors: [{ id: 'big', ready: false, error: 'нет модели' }] })
    const state = makeState({ config: makeConfig(), status })
    render(<div style={{ width: 800, height: 600 }}><SchemaView state={state} actions={makeActions()} /></div>)
    expect(screen.getAllByText('модель недоступна')).toHaveLength(1)
  })

  it('executor link label carries the full condition in title', () => {
    const when = 'я'.repeat(60)
    render(<EdgeLabel text="яя…" title={when} x={10} y={20} />)
    expect(screen.getByTitle(when)).toHaveTextContent('яя…')
    expect(screen.getByTitle(when).style.transform).toContain('translate(10px, 20px)')
  })
})
