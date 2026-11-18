// Маленькая метка состояния с цветной точкой.
import './top.css'

type Props = { text: string; tone: 'ok' | 'warn' | 'bad' | 'off' }

export default function StatusPill({ text, tone }: Props) {
  return (
    <span className="pill">
      <span className={`dot dot-${tone}`} />
      {text}
    </span>
  )
}
