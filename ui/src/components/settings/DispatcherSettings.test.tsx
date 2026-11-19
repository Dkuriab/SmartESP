import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const models = [
  { name: 'qwen3', size_bytes: 5_200_000_000 },
  { name: 'gemma3', size_bytes: 3_300_000_000 },
]

function setup(over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({ config: makeConfig(), models, selected: { kind: 'dispatcher', id: 'dispatcher' }, ...over })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

describe('DispatcherSettings', () => {
  it('модели с размером в ГБ; выбор вызывает setDispatcher({model})', async () => {
    const { actions } = setup()
    const select = screen.getByLabelText('Модель')
    expect(select).toHaveValue('qwen3')
    expect(screen.getByRole('option', { name: 'gemma3 · 3,3 ГБ' })).toBeInTheDocument()
    await userEvent.selectOptions(select, 'gemma3')
    expect(actions.setDispatcher).toHaveBeenCalledWith({ model: 'gemma3' })
  })

  it('Ollama недоступна — выбор заблокирован с подписью, текущая модель видна', () => {
    setup({ models: [], status: makeStatus({ ollama: { reachable: false, loaded: [] } }) })
    expect(screen.getByLabelText('Модель')).toBeDisabled()
    expect(screen.getByLabelText('Модель')).toHaveValue('qwen3')
    expect(screen.getByText('Ollama недоступна')).toBeInTheDocument()
  })

  it('«Сохранить» неактивна без изменений, после правки шлёт промпт', async () => {
    const { actions } = setup()
    const save = screen.getByRole('button', { name: 'Сохранить' })
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Промпт'), '!')
    expect(save).toBeEnabled()
    await userEvent.click(save)
    expect(actions.setDispatcher).toHaveBeenCalledWith({ system_prompt: 'Отвечай коротко!' })
  })

  it('промпт на 20 000 символов — поле фиксированной высоты с прокруткой', () => {
    const long = 'я'.repeat(20000)
    const config = makeConfig({ executors: [{ entry: true, model: 'qwen3', system_prompt: long }] })
    setup({ config })
    const area = screen.getByLabelText('Промпт')
    expect(area).toHaveValue(long)
    expect(area).toHaveAttribute('rows', '8')
    expect(area).toHaveClass('prompt')
  })

  it('пока изменение применяется — «Применяется…» на кнопке', async () => {
    setup({ pending: { 5: 'Диспетчер' } })
    await userEvent.type(screen.getByLabelText('Промпт'), '!')
    const save = screen.getByRole('button', { name: 'Применяется…' })
    expect(save).toBeDisabled()
  })

  it('status.applying тоже показывает «Применяется…»', () => {
    setup({ status: makeStatus({ applying: true }) })
    expect(screen.getByRole('button', { name: 'Применяется…' })).toBeInTheDocument()
  })

  it('нет входного исполнителя — подсказка вместо полей', () => {
    setup({ config: makeConfig({ executors: [] }) })
    expect(screen.getByText('Диспетчер не настроен')).toBeInTheDocument()
  })
})
