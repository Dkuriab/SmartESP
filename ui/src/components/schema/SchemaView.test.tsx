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

describe('SchemaView: живая подсветка', () => {
  const connectors = [{ id: 'calc', name: 'Калькулятор', command: 'uv', enabled: true }]
  const live = {
    executors: { dispatcher: { state: 'thinking' as const, turn: 'a#1' } },
    connectors: { calc: { tool: 'calc_add', executor: 'dispatcher', turn: 'a#1' } },
  }

  function draw(over = {}) {
    const status = makeStatus({
      ollama: { reachable: true, loaded: ['qwen3:latest'] },
      connectors: [{ id: 'calc', name: 'Калькулятор', state: 'ready', tools: ['calc_add'], error: '' }],
    })
    const state = makeState({ config: makeConfig({ connectors }), status, ...over })
    render(<div style={{ width: 800, height: 600 }}><SchemaView state={state} actions={makeActions()} /></div>)
  }

  it('работающие узлы пульсируют с подписью', () => {
    draw({ live })
    const thinking = screen.getByText('думает…')
    expect(thinking.closest('.node')).toHaveClass('live')
    expect(screen.getByText('calc_add…').closest('.node')).toHaveClass('live')
  })

  it('без работы подписей нет; модель в памяти отмечена', () => {
    draw()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByText('· в памяти', { exact: false })).toBeInTheDocument()
  })

  it('клик по коннектору выбирает его', () => {
    const actions = makeActions()
    const state = makeState({ config: makeConfig({ connectors }) })
    render(<div style={{ width: 800, height: 600 }}><SchemaView state={state} actions={actions} /></div>)
    fireEvent.click(screen.getByText('Калькулятор'))
    expect(actions.select).toHaveBeenCalledWith({ kind: 'connector', id: 'calc' })
  })
})
