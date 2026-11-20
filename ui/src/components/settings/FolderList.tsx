// Список папок «имя = путь»: строки можно добавлять, править и убирать.
import type { FolderRow } from './connectorValues'

type Props = {
  title: string
  rows: FolderRow[]
  disabled: boolean
  onChange: (rows: FolderRow[]) => void
}

export default function FolderList({ title, rows, disabled, onChange }: Props) {
  const put = (i: number, row: FolderRow) => onChange(rows.map((r, j) => (j === i ? row : r)))
  return (
    <div className="folder-list">
      {rows.map((row, i) => (
        <div key={i} className="folder-row">
          <input
            className="val folder-name"
            aria-label={`${title}: имя ${i + 1}`}
            placeholder="имя"
            value={row.name}
            disabled={disabled}
            onChange={(e) => put(i, { ...row, name: e.target.value })}
          />
          <input
            className="val folder-path"
            aria-label={`${title}: путь ${i + 1}`}
            placeholder="/Users/…/папка"
            value={row.path}
            disabled={disabled}
            onChange={(e) => put(i, { ...row, path: e.target.value })}
          />
          <button
            type="button"
            className="chip"
            aria-label={`Убрать папку ${i + 1}`}
            disabled={disabled}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="chip"
        disabled={disabled}
        onClick={() => onChange([...rows, { name: '', path: '' }])}
      >
        + папка
      </button>
    </div>
  )
}
