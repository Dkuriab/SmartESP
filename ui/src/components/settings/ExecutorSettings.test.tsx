import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

const models = [
  { name: 'qwen3', size_bytes: 5_200_000_000, supports_tools: true },
  { name: 'gemma3', size_bytes: 3_300_000_000, supports_tools: true },
  { name: 'tiny', size_bytes: 1_000_000_000, supports_tools: false },
]

const dispatcher = {
  id: 'dispatcher',
  name: 'Диспетчер',
  entry: true,
  model: 'qwen3',
  system_prompt: 'Отвечай коротко',
  delegates: [{ to: 'big', when: 'сложное' }],
}
const big = { id: 'big', name: 'Большая модель', entry: false, model: 'gemma3', description: 'расчёты', system_prompt: 'Ты большая', delegates: [] }
const small = { id: 'small', name: 'Малая', entry: false, model: 'qwen3', description: '', delegates: [] }

function config(executors: unknown[] = [dispatcher, big, small]) {
  return {
    ...makeConfig({ executors }),
    executor_prompts: { dispatcher: 'Отвечай коротко\nПравило шёпота', big: 'Ты большая\nПравило передачи' },
  }
}

function setup(id = 'dispatcher', over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({ config: config(), models, selected: { kind: 'executor', id }, ...over })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

const linkRow = (name: string) => screen.getByRole('group', { name })

describe('ExecutorSettings: поля', () => {
  it('входной: заголовок, итоговый промпт свёрнут и только для чтения, «Удалить» нет', async () => {
    setup()
    expect(screen.getByRole('heading')).toHaveTextContent('Диспетчер')
    expect(screen.queryByRole('button', { name: 'Удалить' })).not.toBeInTheDocument()
    const summary = screen.getByText('Итоговый промпт')
    const details = summary.closest('details')
    expect(details).not.toHaveAttribute('open')
    await userEvent.click(summary)
    expect(details).toHaveAttribute('open')
    expect(within(details as HTMLElement).getByText(/Правило шёпота/).tagName).toBe('PRE')
  })

  it('старый выбор «dispatcher» открывает входного', () => {
    setup('x', { selected: { kind: 'dispatcher', id: 'dispatcher' } })
    expect(screen.getByLabelText('Имя')).toHaveValue('Диспетчер')
  })

  it('имя: Enter шлёт updateExecutor, пустое и прежнее — не шлёт', async () => {
    const { actions } = setup('big')
    const input = screen.getByLabelText('Имя')
    await userEvent.click(input)
    await userEvent.tab()
    await userEvent.clear(input)
    await userEvent.tab()
    expect(actions.updateExecutor).not.toHaveBeenCalled()
    expect(input).toHaveValue('Большая модель')
    await userEvent.clear(input)
    await userEvent.type(input, 'Умная{Enter}')
    expect(actions.updateExecutor).toHaveBeenCalledTimes(1)
    expect(actions.updateExecutor).toHaveBeenCalledWith('big', { name: 'Умная' })
  })

  it('описание сохраняется по потере фокуса', async () => {
    const { actions } = setup('big')
    await userEvent.type(screen.getByLabelText('Описание'), ' и код')
    await userEvent.tab()
    expect(actions.updateExecutor).toHaveBeenCalledWith('big', { description: 'расчёты и код' })
  })

  it('модели с размером и «(без инструментов)»; выбор шлёт updateExecutor', async () => {
    const { actions } = setup()
    const select = screen.getByLabelText('Модель')
    expect(select).toHaveValue('qwen3')
    expect(screen.getByRole('option', { name: 'gemma3 · 3,3 ГБ' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'tiny · 1,0 ГБ (без инструментов)' })).toBeInTheDocument()
    await userEvent.selectOptions(select, 'gemma3')
    expect(actions.updateExecutor).toHaveBeenCalledWith('dispatcher', { model: 'gemma3' })
  })

  it('«Рассуждение»: по умолчанию «Нет», выбор шлёт updateExecutor', async () => {
    const { actions } = setup()
    const select = screen.getByLabelText('Рассуждение')
    expect(select).toHaveValue('off')
    expect(screen.getAllByRole('option', { name: /^(Нет|Низкое|Среднее|Высокое)$/ })).toHaveLength(4)
    await userEvent.selectOptions(select, 'low')
    expect(actions.updateExecutor).toHaveBeenCalledWith('dispatcher', { reasoning: 'low' })
  })

  it('«Рассуждение» показывает уровень из настроек', () => {
    setup('big', { config: config([dispatcher, { ...big, reasoning: 'medium' }, small]) })
    expect(screen.getByLabelText('Рассуждение')).toHaveValue('medium')
  })

  it('подсказка: модель не gpt-oss с уровнем может не уметь рассуждать', () => {
    setup('big', { config: config([dispatcher, { ...big, reasoning: 'low' }, small]) })
    expect(screen.getByText(/может не поддерживать рассуждение/)).toBeInTheDocument()
  })

  it('подсказка: у gpt-oss «Нет» — это «Низкое»; без уровня у другой модели подсказки нет', () => {
    setup('dispatcher', { config: config([{ ...dispatcher, model: 'gpt-oss:20b' }, big, small]) })
    expect(screen.getByText(/рассуждение не выключается/)).toBeInTheDocument()
    expect(screen.queryByText(/может не поддерживать/)).not.toBeInTheDocument()
  })

  it('без уровня у обычной модели подсказки нет', () => {
    setup('big')
    expect(screen.queryByText(/рассуждени.* (не выключается|может не поддерживать)/)).not.toBeInTheDocument()
  })

  it('Ollama недоступна — выбор заблокирован с подписью, текущая модель видна', () => {
    setup('dispatcher', { models: [], status: makeStatus({ ollama: { reachable: false, loaded: [] } }) })
    expect(screen.getByLabelText('Модель')).toBeDisabled()
    expect(screen.getByLabelText('Модель')).toHaveValue('qwen3')
    expect(screen.getByText('Ollama недоступна')).toBeInTheDocument()
  })

  it('«Сохранить» неактивна без изменений, после правки шлёт промпт', async () => {
    const { actions } = setup()
    const save = screen.getByRole('button', { name: 'Сохранить' })
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Промпт'), '!')
    await userEvent.click(save)
    expect(actions.updateExecutor).toHaveBeenCalledWith('dispatcher', { systemPrompt: 'Отвечай коротко!' })
  })

  it('промпт на 20 000 символов — поле фиксированной высоты с прокруткой', () => {
    const long = 'я'.repeat(20000)
    setup('dispatcher', { config: config([{ ...dispatcher, system_prompt: long }]) })
    const area = screen.getByLabelText('Промпт')
    expect(area).toHaveValue(long)
    expect(area).toHaveAttribute('rows', '8')
    expect(area).toHaveClass('prompt')
  })

  it('не входной показывает свой итоговый промпт', () => {
    setup('big')
    expect(screen.getByText(/Правило передачи/)).toBeInTheDocument()
  })

  it('пока применяется — всё заблокировано, «Применяется…» на кнопке', async () => {
    setup('big', { pending: { 5: 'Исполнитель' } })
    await userEvent.type(screen.getByLabelText('Промпт'), '!')
    expect(screen.getByRole('button', { name: 'Применяется…' })).toBeDisabled()
    for (const label of ['Модель', 'Имя', 'Описание']) expect(screen.getByLabelText(label)).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Удалить' })).toBeDisabled()
    expect(within(linkRow('Диспетчер')).getByRole('checkbox')).toBeDisabled()
  })

  it('status.applying тоже показывает «Применяется…»', () => {
    setup('dispatcher', { status: makeStatus({ applying: true }) })
    expect(screen.getByRole('button', { name: 'Применяется…' })).toBeInTheDocument()
  })
})

describe('ExecutorSettings: «Может передавать»', () => {
  it('строка на каждого другого исполнителя; заглушка — описание цели', () => {
    setup()
    expect(screen.queryByRole('group', { name: 'Диспетчер' })).not.toBeInTheDocument()
    const when = within(linkRow('Большая модель')).getByLabelText('Когда вызывать')
    expect(when).toHaveValue('сложное')
    expect(when).toHaveAttribute('placeholder', 'расчёты')
    expect(within(linkRow('Большая модель')).getByRole('checkbox')).toBeChecked()
    expect(within(linkRow('Малая')).getByRole('checkbox')).not.toBeChecked()
  })

  it('флажок вызывает setLink', async () => {
    const { actions } = setup()
    await userEvent.click(within(linkRow('Малая')).getByRole('checkbox'))
    expect(actions.setLink).toHaveBeenCalledWith('dispatcher', 'small', true, '')
    await userEvent.click(within(linkRow('Большая модель')).getByRole('checkbox'))
    expect(actions.setLink).toHaveBeenCalledWith('dispatcher', 'big', false, 'сложное')
  })

  it('условие сохраняется по Enter; по потере фокуса включает связь', async () => {
    const { actions } = setup()
    await userEvent.type(within(linkRow('Большая модель')).getByLabelText('Когда вызывать'), ' и код{Enter}')
    expect(actions.setLink).toHaveBeenCalledWith('dispatcher', 'big', true, 'сложное и код')
    await userEvent.type(within(linkRow('Малая')).getByLabelText('Когда вызывать'), 'мелочи')
    await userEvent.tab()
    expect(actions.setLink).toHaveBeenCalledWith('dispatcher', 'small', true, 'мелочи')
    expect(actions.setLink).toHaveBeenCalledTimes(2)
  })

  it('пустое условие при пустом описании цели — «неактивна»', () => {
    const entry = { ...dispatcher, delegates: [...dispatcher.delegates, { to: 'small', when: '' }] }
    setup('dispatcher', { config: config([entry, big, small]) })
    expect(within(linkRow('Малая')).getByText('неактивна — укажите, когда вызывать')).toBeInTheDocument()
    expect(within(linkRow('Большая модель')).queryByText(/неактивна/)).not.toBeInTheDocument()
  })

  it('у выключенной связи — подсказка, что ввод условия её включит', () => {
    setup()
    expect(within(linkRow('Малая')).getByText('ввод условия включит связь')).toBeInTheDocument()
    expect(within(linkRow('Большая модель')).queryByText('ввод условия включит связь')).not.toBeInTheDocument()
  })

  it('модель без инструментов — пометка, новые связи не добавить, условия не править', () => {
    setup('dispatcher', { config: config([{ ...dispatcher, model: 'tiny' }, big, small]) })
    expect(screen.getByText('эта модель не умеет передавать задачи')).toBeInTheDocument()
    expect(within(linkRow('Малая')).getByRole('checkbox')).toBeDisabled()
    expect(within(linkRow('Малая')).getByLabelText('Когда вызывать')).toBeDisabled()
    expect(within(linkRow('Малая')).queryByText('ввод условия включит связь')).not.toBeInTheDocument()
    expect(within(linkRow('Большая модель')).getByLabelText('Когда вызывать')).toBeDisabled()
  })

  it('модель без инструментов — существующую связь можно убрать', async () => {
    const { actions } = setup('dispatcher', { config: config([{ ...dispatcher, model: 'tiny' }, big, small]) })
    const box = within(linkRow('Большая модель')).getByRole('checkbox')
    expect(box).toBeEnabled()
    await userEvent.click(box)
    expect(actions.setLink).toHaveBeenCalledWith('dispatcher', 'big', false, 'сложное')
  })

  it('модель не прогрелась — «модель недоступна»', () => {
    const status = makeStatus({ executors: [{ id: 'big', ready: false, error: 'нет модели' }] })
    setup('big', { status })
    expect(screen.getByText('модель недоступна')).toBeInTheDocument()
  })

  it('модель прогрелась — без пометки', () => {
    setup('big', { status: makeStatus({ executors: [{ id: 'big', ready: true, error: null }] }) })
    expect(screen.queryByText('модель недоступна')).not.toBeInTheDocument()
  })
})

describe('ExecutorSettings: удаление', () => {
  it('«Удалить» спрашивает на месте; «Отмена» — ничего, «Удалить» — removeExecutor', async () => {
    const { actions } = setup('big')
    await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
    expect(screen.getByText('Удалить «Большая модель»? Связи на него тоже уберутся.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Отмена' }))
    expect(actions.removeExecutor).not.toHaveBeenCalled()
    expect(screen.queryByText(/Связи на него/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
    await userEvent.click(screen.getByRole('button', { name: 'Удалить' }))
    expect(actions.removeExecutor).toHaveBeenCalledWith('big')
  })
})
