import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState } from '../fixtures'
import SpeechSettings from './SpeechSettings'

function setup(speech: unknown, over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({ config: makeConfig({ speech }), ...over })
  render(<SpeechSettings state={state} actions={actions} />)
  return { actions }
}

describe('SpeechSettings', () => {
  it('переключатели отражают config.speech', () => {
    setup({ proactive: true, listen_after_question: false })
    expect(screen.getByRole('checkbox', { name: 'Кузя может заговорить сам' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Слушать после вопроса' })).not.toBeChecked()
  })

  it('клик шлёт только свой ключ', async () => {
    const { actions } = setup({ proactive: true, listen_after_question: true })
    await userEvent.click(screen.getByRole('checkbox', { name: 'Кузя может заговорить сам' }))
    expect(actions.patchConfig).toHaveBeenCalledWith({ speech: { proactive: false } }, expect.any(String))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Слушать после вопроса' }))
    expect(actions.patchConfig).toHaveBeenCalledWith({ speech: { listen_after_question: false } }, expect.any(String))
  })

  it('во время применения заблокированы', () => {
    setup({ proactive: true, listen_after_question: true }, { status: { ...makeState().status!, applying: true } })
    expect(screen.getByRole('checkbox', { name: 'Кузя может заговорить сам' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Слушать после вопроса' })).toBeDisabled()
  })
})
