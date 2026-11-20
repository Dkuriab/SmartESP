import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { CoreState, Selection } from '../../state/model'
import { makeActions, makeConfig, makeState, makeStatus } from '../fixtures'
import SettingsPanel from './SettingsPanel'

function setup(selected: Selection | null, over: Partial<CoreState> = {}) {
  const actions = makeActions()
  const state = makeState({ config: makeConfig(), selected, ...over })
  render(<SettingsPanel state={state} actions={actions} />)
  return { actions }
}

const seenAt = new Date(2024, 0, 2, 9, 5).getTime() / 1000
const devices = [
  { device_id: 'aa:bb', name: 'Спальня', connected: true, remote: '192.168.1.20:5123', fw: '1.4', protocol: 2 },
  { device_id: 'cc:dd', name: '', connected: false, remote: '', fw: '', last_seen: seenAt, protocol: 0 },
]

describe('SettingsPanel', () => {
  it('без выбора — подсказка', () => {
    setup(null)
    expect(screen.getByText('Выберите блок на схеме или в списке')).toBeInTheDocument()
  })

  it('колонка: переименование по Enter вызывает renameDevice', async () => {
    const { actions } = setup({ kind: 'device', id: 'aa:bb' }, { status: makeStatus({ devices }) })
    const input = screen.getByLabelText('Имя')
    await userEvent.clear(input)
    await userEvent.type(input, 'Кухня{Enter}')
    expect(actions.renameDevice).toHaveBeenCalledTimes(1)
    expect(actions.renameDevice).toHaveBeenCalledWith('aa:bb', 'Кухня')
  })

  it('колонка: имя не изменилось — потеря фокуса ничего не шлёт', async () => {
    const { actions } = setup({ kind: 'device', id: 'aa:bb' }, { status: makeStatus({ devices }) })
    await userEvent.click(screen.getByLabelText('Имя'))
    await userEvent.tab()
    expect(actions.renameDevice).not.toHaveBeenCalled()
  })

  it('колонка: MAC, IP, прошивка, в сети', () => {
    setup({ kind: 'device', id: 'aa:bb' }, { status: makeStatus({ devices }) })
    expect(screen.getByText('aa:bb')).toBeInTheDocument()
    expect(screen.getByText('192.168.1.20')).toBeInTheDocument()
    expect(screen.getByText('1.4')).toBeInTheDocument()
    expect(screen.getByText('в сети')).toBeInTheDocument()
  })

  it.each([
    ['[fe80::1]:5123', 'fe80::1'],
    ['fe80::1', 'fe80::1'],
    ['kitchen.local:80', 'kitchen.local'],
  ])('колонка: адрес %s показывается как %s', (remote, host) => {
    const status = makeStatus({ devices: [{ ...devices[0]!, remote }] })
    setup({ kind: 'device', id: 'aa:bb' }, { status })
    expect(screen.getByText(host)).toBeInTheDocument()
  })

  it('колонка: черновик имени сбрасывается, когда имя сменилось извне', async () => {
    const actions = makeActions()
    const at = (name: string) =>
      makeState({ status: makeStatus({ devices: [{ ...devices[0]!, name }] }), selected: { kind: 'device', id: 'aa:bb' } })
    const view = render(<SettingsPanel state={at('Спальня')} actions={actions} />)
    await userEvent.type(screen.getByLabelText('Имя'), ' 2')
    view.rerender(<SettingsPanel state={at('Детская')} actions={actions} />)
    expect(screen.getByLabelText('Имя')).toHaveValue('Детская')
  })

  it('колонка без имени и не в сети: MAC в заголовке, «была в HH:MM»', () => {
    setup({ kind: 'device', id: 'cc:dd' }, { status: makeStatus({ devices }) })
    expect(screen.getByRole('heading')).toHaveTextContent('cc:dd')
    expect(screen.getByText('была в 09:05')).toBeInTheDocument()
  })

  it('колонка только из настроек — «не подключалась»', () => {
    const config = makeConfig({ devices: { 'ee:ff': { name: 'Гараж' } } })
    setup({ kind: 'device', id: 'ee:ff' }, { config })
    expect(screen.getByLabelText('Имя')).toHaveValue('Гараж')
    expect(screen.getByText('не подключалась')).toBeInTheDocument()
  })

  it('обработчик: выключение шлёт список без него', async () => {
    const { actions } = setup({ kind: 'stage', id: 'whisper_detect' })
    expect(screen.getByText('Шёпот: замечает, что вопрос сказан шёпотом (видно в ленте)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('switch', { name: 'Включён' }))
    expect(actions.setStages).toHaveBeenCalledWith([])
  })

  it('обработчик: включение добавляет {kind}', async () => {
    const { actions } = setup({ kind: 'stage', id: 'whisper_detect' }, { config: makeConfig({ stages: [] }) })
    const sw = screen.getByRole('switch', { name: 'Включён' })
    expect(sw).not.toBeChecked()
    await userEvent.click(sw)
    expect(actions.setStages).toHaveBeenCalledWith([{ kind: 'whisper_detect' }])
  })

  it('обработчик: настройки не загружены — переключатель заблокирован', () => {
    setup({ kind: 'stage', id: 'whisper_detect' }, { config: null })
    expect(screen.getByRole('switch', { name: 'Включён' })).toBeDisabled()
    expect(screen.queryByText('Применяется…')).not.toBeInTheDocument()
  })

  it('обработчик: пока применяется — «Применяется…» и переключатель заблокирован', () => {
    setup({ kind: 'stage', id: 'whisper_detect' }, { pending: { 3: 'Обработчики' } })
    expect(screen.getByText('Применяется…')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Включён' })).toBeDisabled()
  })

  it('шёпот: «Отвечать тише» выключено по умолчанию, с честной подсказкой', () => {
    setup({ kind: 'stage', id: 'whisper_detect' })
    expect(screen.getByRole('switch', { name: 'Отвечать тише на шёпот' })).not.toBeChecked()
    expect(screen.getByText('Это не настоящий шёпот: голос просто тише')).toBeInTheDocument()
  })

  it('шёпот: включение «Отвечать тише» шлёт stages с quiet_reply', async () => {
    const { actions } = setup({ kind: 'stage', id: 'whisper_detect' })
    await userEvent.click(screen.getByRole('switch', { name: 'Отвечать тише на шёпот' }))
    expect(actions.setStages).toHaveBeenCalledWith([{ kind: 'whisper_detect', timeout_ms: 50, quiet_reply: true }])
  })

  it('шёпот: выключенный обработчик — «Отвечать тише» заблокировано', () => {
    setup({ kind: 'stage', id: 'whisper_detect' }, { config: makeConfig({ stages: [] }) })
    expect(screen.getByRole('switch', { name: 'Отвечать тише на шёпот' })).toBeDisabled()
  })

  it('время: своих переключателей нет', () => {
    setup({ kind: 'stage', id: 'clock' })
    expect(screen.getAllByRole('switch')).toHaveLength(1)
  })

  it('колонка со старой прошивкой в сети — подсказка обновить', () => {
    const old = [{ ...devices[0]!, protocol: 2 }]
    setup({ kind: 'device', id: 'aa:bb' }, { status: makeStatus({ devices: old }) })
    expect(screen.getByText('Обновите прошивку, чтобы Кузя мог говорить сам')).toBeInTheDocument()
  })

  it('подсказки нет: новая прошивка или колонка не в сети', () => {
    const fresh = [{ ...devices[0]!, protocol: 3 }, { ...devices[1]!, protocol: 2 }]
    setup({ kind: 'device', id: 'aa:bb' }, { status: makeStatus({ devices: fresh }) })
    expect(screen.queryByText(/Обновите прошивку/)).not.toBeInTheDocument()
  })
})
