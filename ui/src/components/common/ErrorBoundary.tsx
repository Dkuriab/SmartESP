// Ловушка ошибок отрисовки: вместо пустого экрана — сообщение и «Обновить».
import { Component } from 'react'
import type { ReactNode } from 'react'
import './common.css'

type Props = {
  children: ReactNode
  /** Перезагрузка страницы (в тестах — поддельная). */
  onReload?: () => void
}

export default class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children
    const reload = this.props.onReload ?? (() => window.location.reload())
    return (
      <div className="token-screen" role="alert">
        <div className="panel token-form">
          <p>Что-то пошло не так</p>
          <button type="button" className="btn" onClick={reload}>
            Обновить
          </button>
        </div>
      </div>
    )
  }
}
