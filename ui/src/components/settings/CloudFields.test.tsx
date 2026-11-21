import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CloudModel } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import { cloudModelNote, modelForKind, priceText } from './CloudFields'
import SettingsPanel from './SettingsPanel'

const flash: CloudModel = { id: 'google/gemini-2.5-flash', name: 'Gemini 2.5 Flash', tools: true, prompt_price: 0.3, completion_price: 2.5 }
const noTools: CloudModel = { id: 'x/plain', name: 'Plain', tools: false, prompt_price: 0, completion_price: 0 }
const local = [{ name: 'qwen3', size_bytes: 1, supports_tools: true }]

function setup(executor: Record<string, unknown>, cloud: Record<string, unknown> = { name: 'OpenRouter', api_key: '' }) {
  const actions = makeActions()
  actions.loadCloudModels = vi.fn().mockResolvedValue([flash, noTools])
  const config = makeConfig({ executors: [{ id: 'd', name: 'Диспетчер', entry: true, delegates: [], ...executor }], cloud })
  const state = makeState({ config, models: local, selected: { kind: 'executor', id: 'd' }, status: makeStatus() })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

describe('CloudFields', () => {
  it('переход в облако: вид cloud и модель по умолчанию; обратно — локальная модель', async () => {
    const { actions } = setup({ model: 'qwen3' })
    await userEvent.selectOptions(screen.getByLabelText('Где работает'), 'cloud')
    expect(actions.updateExecutor).toHaveBeenCalledWith('d', { kind: 'cloud', model: 'google/gemini-2.5-flash' })
    expect(modelForKind('ollama', local)).toBe('qwen3')
    expect(modelForKind('ollama', [])).toBe('gpt-oss:20b')
  })

  it('облачная модель: цена из списка, своя модель по Enter, ключ не задан — подсказка', async () => {
    const { actions } = setup({ kind: 'cloud', model: 'google/gemini-2.5-flash' })
    expect(await screen.findByText(/\$0.3 вход \/ \$2.5 ответ/)).toBeInTheDocument()
    expect(screen.getByText(/Без ключа модель не ответит/)).toBeInTheDocument()
    expect(screen.getByText(/уходит в облако/)).toBeInTheDocument()
    const field = screen.getByLabelText('Модель')
    await userEvent.clear(field)
    await userEvent.type(field, 'x/plain{Enter}')
    expect(actions.updateExecutor).toHaveBeenCalledWith('d', { model: 'x/plain' })
  })

  it('ключ: поле пароля, «Сохранить ключ» отправляет и очищает; заданный ключ не показывается', async () => {
    const { actions } = setup({ kind: 'cloud', model: 'google/gemini-2.5-flash' }, { name: 'OpenRouter', api_key: '•••' })
    const key = screen.getByLabelText('Ключ OpenRouter')
    expect(key).toHaveAttribute('type', 'password')
    expect(key).toHaveValue('')
    expect(screen.queryByText(/Без ключа/)).not.toBeInTheDocument()
    await userEvent.type(key, ' sk-or-1 ')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить ключ' }))
    expect(actions.setCloudKey).toHaveBeenCalledWith('sk-or-1')
    expect(key).toHaveValue('')
  })

  it('пометки модели: нет инструментов, нет в списке, бесплатно', () => {
    expect(cloudModelNote('x/plain', [flash, noTools]).warn).toBe(true)
    expect(cloudModelNote('y/none', [flash]).text).toBe('такой модели нет в списке сервиса')
    expect(cloudModelNote('y/none', []).text).toBe('')
    expect(priceText(noTools)).toBe('бесплатно')
  })
})
