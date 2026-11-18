// Корень интерфейса: состояние ядра и каркас экрана.
import Shell from './components/layout/Shell'
import { useCore } from './state/useCore'

export default function App() {
  const [state, actions] = useCore()
  return <Shell state={state} actions={actions} />
}
