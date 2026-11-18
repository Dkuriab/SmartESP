// Экран ввода токена: показывается, когда ядро ответило «нет доступа».
import { useState } from 'react'
import './common.css'

type Props = { onToken: (token: string) => void }

export default function TokenScreen({ onToken }: Props) {
  const [value, setValue] = useState('')
  function submit(e: React.FormEvent) {
    e.preventDefault()
    const token = value.trim()
    if (token) onToken(token)
  }
  return (
    <div className="token-screen">
      <form className="panel token-form" onSubmit={submit}>
        <label htmlFor="token-input">Введите токен</label>
        <input
          id="token-input"
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button type="submit" className="btn">
          Войти
        </button>
      </form>
    </div>
  )
}
