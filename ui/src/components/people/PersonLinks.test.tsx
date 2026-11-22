import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ConnectorDetail } from '../../state/model'
import type { Person } from '../../state/peopleActions'
import { makeActions, makeState } from '../fixtures'
import { parsePairs } from './knownAccounts'
import PeopleTab from './PeopleTab'

const anya: Person = {
  id: 'a1',
  name: 'Аня',
  created_at: 1,
  samples: [],
  stale_samples: 0,
  links: [{ channel: 'telegram', account: '111' }],
}
const bob: Person = { ...anya, id: 'b2', name: 'Боб', created_at: 2, links: [] }
const bot: ConnectorDetail = {
  id: 'telegram',
  name: 'Telegram-бот',
  state: 'ready',
  tools: [],
  error: '',
  kind: 'client',
  note: '',
  example: '',
  settings: [{ key: 'TELEGRAM_USERS', title: 'Кому отвечать', type: 'pairs', hint: '', value: '111=Аня;222=Боб' }],
}

function setup() {
  const actions = makeActions()
  actions.loadPeople = vi.fn().mockResolvedValue([anya, bob])
  render(<PeopleTab state={makeState({ connectors: [bot] })} actions={actions} />)
  return { actions }
}

describe('PersonLinks', () => {
  it('связь показана с именем из бота; убрать — в ядро', async () => {
    const { actions } = setup()
    expect(await screen.findByText('Telegram · Аня id 111')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Убрать связь telegram 111' }))
    expect(actions.removeLink).toHaveBeenCalledWith('a1', 'telegram', '111')
  })

  it('связать: предлагаются только свободные пользователи бота или вручную', async () => {
    const { actions } = setup()
    await userEvent.click(await screen.findByRole('button', { name: /Боб/ }))
    const pick = screen.getByLabelText('Кого связать')
    expect(screen.queryByRole('option', { name: /Аня/ })).toBeNull() // Аня уже связана
    await userEvent.click(screen.getByRole('button', { name: 'Связать' }))
    expect(actions.addLink).toHaveBeenCalledWith('b2', 'telegram', '222')
    await userEvent.selectOptions(pick, 'manual')
    await userEvent.clear(screen.getByLabelText('Канал'))
    await userEvent.type(screen.getByLabelText('Канал'), 'matrix')
    await userEvent.type(screen.getByLabelText('Аккаунт'), '@bob:home')
    await userEvent.click(screen.getByRole('button', { name: 'Связать' }))
    expect(actions.addLink).toHaveBeenLastCalledWith('b2', 'matrix', '@bob:home')
  })

  it('разбор «id=имя;…»', () => {
    expect(parsePairs(' 111 = Аня ;bad; =x;222=Б=оря')).toEqual([
      { account: '111', name: 'Аня' },
      { account: '222', name: 'Б=оря' },
    ])
  })
})
