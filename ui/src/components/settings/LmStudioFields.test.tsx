import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { LmStudioModel } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import { lmStudioModelLabel, pickLmStudioModel } from './LmStudioFields'
import SettingsPanel from './SettingsPanel'

const qwen: LmStudioModel = { id: 'qwen/qwen3-8b', name: 'Qwen3 8B', loaded: false, tools: true }
const gemma: LmStudioModel = { id: 'google/gemma-3-12b', name: 'Gemma 3 12B', loaded: true, tools: false }
const plain: LmStudioModel = { id: 'plain', name: 'plain', loaded: null, tools: null }

function setup(executor: Record<string, unknown>, list = { models: [gemma, qwen], error: '' }, lmstudio: Record<string, unknown> = { base_url: 'http://localhost:1234', api_key: '' }) {
  const actions = makeActions()
  actions.loadLmStudioModels = vi.fn().mockResolvedValue(list)
  const config = makeConfig({ executors: [{ id: 'd', name: 'Кузя', entry: true, delegates: [], ...executor }], lmstudio })
  const state = makeState({ config, models: [], selected: { kind: 'executor', id: 'd' }, status: makeStatus() })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

describe('LmStudioFields', () => {
  it('выбор «LM Studio»: вид lmstudio и загруженная модель из списка', async () => {
    const { actions } = setup({ model: 'gpt-oss:20b' })
    await userEvent.selectOptions(screen.getByLabelText('Где работает'), 'lmstudio')
    expect(actions.updateExecutor).toHaveBeenCalledWith('d', { kind: 'lmstudio', model: 'google/gemma-3-12b' })
  })

  it('модели с пометками «загружена» и «без родных инструментов»; выбор шлёт модель', async () => {
    const { actions } = setup({ kind: 'lmstudio', model: 'qwen/qwen3-8b' })
    expect(await screen.findByRole('option', { name: 'Gemma 3 12B · загружена · без родных инструментов' })).toBeInTheDocument()
    const field = screen.getByLabelText('Модель')
    expect(screen.getByText(/не загружена: LM Studio загрузит её/)).toBeInTheDocument()
    await userEvent.selectOptions(field, 'google/gemma-3-12b')
    expect(actions.updateExecutor).toHaveBeenCalledWith('d', { model: 'google/gemma-3-12b' })
  })

  it('сервер не запущен: ошибка у поля, модель вводится вручную', async () => {
    const error = 'Сервер LM Studio не запущен по адресу http://localhost:1234'
    const { actions } = setup({ kind: 'lmstudio', model: 'qwen/qwen3-8b' }, { models: [], error })
    expect(await screen.findByText(error)).toBeInTheDocument()
    const field = screen.getByLabelText('Модель')
    await userEvent.clear(field)
    await userEvent.type(field, 'mistral-7b{Enter}')
    expect(actions.updateExecutor).toHaveBeenCalledWith('d', { model: 'mistral-7b' })
  })

  it('адрес сохраняется по Enter, ключ — поле пароля; заданный ключ не показывается', async () => {
    const { actions } = setup({ kind: 'lmstudio', model: 'qwen/qwen3-8b' }, undefined, { base_url: 'http://localhost:1234', api_key: '•••' })
    const address = screen.getByLabelText('Адрес LM Studio')
    await userEvent.clear(address)
    await userEvent.type(address, 'http://mac.local:1234{Enter}')
    expect(actions.setLmStudio).toHaveBeenCalledWith({ base_url: 'http://mac.local:1234' }, 'Адрес LM Studio')
    expect(screen.getByText(/смена адреса сбрасывает ключ/)).toBeInTheDocument()
    const key = screen.getByLabelText('Ключ LM Studio')
    expect(key).toHaveAttribute('type', 'password')
    expect(key).toHaveValue('')
    await userEvent.type(key, ' lm-1 ')
    await userEvent.click(screen.getByRole('button', { name: 'Сохранить ключ' }))
    expect(actions.setLmStudio).toHaveBeenCalledWith({ api_key: 'lm-1' }, 'Ключ LM Studio')
  })

  it('подписи и модель по умолчанию', () => {
    expect(lmStudioModelLabel(qwen)).toBe('Qwen3 8B · инструменты')
    expect(lmStudioModelLabel(plain)).toBe('plain')
    expect(pickLmStudioModel([qwen, gemma], 'x')).toBe('google/gemma-3-12b')
    expect(pickLmStudioModel([qwen], 'x')).toBe('qwen/qwen3-8b')
    expect(pickLmStudioModel([], 'x')).toBe('x')
  })
})
