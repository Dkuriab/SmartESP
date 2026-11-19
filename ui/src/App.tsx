// Корень интерфейса: состояние ядра и каркас экрана; ошибка отрисовки не даёт пустой экран.
import ErrorBoundary from './components/common/ErrorBoundary'
import Shell from './components/layout/Shell'
import { useCore } from './state/useCore'

export default function App() {
  const [state, actions] = useCore()
  return (
    <ErrorBoundary>
      <Shell state={state} actions={actions} />
    </ErrorBoundary>
  )
}
