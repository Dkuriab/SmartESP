import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AccessInfo from './AccessInfo'

const URL_1 = 'http://192.168.1.5:8765/?token=t'

describe('AccessInfo', () => {
  it('показывает адреса; «Скопировать» кладёт адрес в буфер', async () => {
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    render(<AccessInfo loadAccess={() => Promise.resolve([URL_1])} online />)
    expect(await screen.findByText(URL_1)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Скопировать' }))
    expect(writeText).toHaveBeenCalledWith(URL_1)
    expect(await screen.findByRole('button', { name: 'Скопировано' })).toBeInTheDocument()
  })

  it('пустой список — «Адрес в сети не найден»', async () => {
    render(<AccessInfo loadAccess={() => Promise.resolve([])} online />)
    expect(await screen.findByText('Адрес в сети не найден')).toBeInTheDocument()
  })

  it('без буфера обмена (http в сети) не падает', async () => {
    const user = userEvent.setup()
    render(<AccessInfo loadAccess={() => Promise.resolve([URL_1])} online />)
    await screen.findByText(URL_1)
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true })
    await user.click(screen.getByRole('button', { name: 'Скопировать' }))
    expect(screen.getByText(URL_1)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Скопировать' })).toBeInTheDocument()
  })
})

describe('AccessInfo без связи', () => {
  it('не запрашивает адреса, пока связи нет, и запрашивает при подключении', async () => {
    const loadAccess = vi.fn().mockResolvedValue([URL_1])
    const view = render(<AccessInfo loadAccess={loadAccess} online={false} />)
    expect(loadAccess).not.toHaveBeenCalled()
    view.rerender(<AccessInfo loadAccess={loadAccess} online />)
    expect(await screen.findByText(URL_1)).toBeInTheDocument()
    view.rerender(<AccessInfo loadAccess={loadAccess} online={false} />)
    expect(screen.getByText(URL_1)).toBeInTheDocument()
  })
})
