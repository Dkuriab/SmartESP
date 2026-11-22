// Сколько записей каждой фразы у каждого человека; строка выбирает фразу для записи.
import type { TrainKit } from '../../state/trainingActions'

/** Сколько записей фразы на человека стоит набрать: главная фраза цели — 50, остальные — 30, «нет» — 20. */
export function goalFor(kit: TrainKit, phrase: string): number {
  if (kit.targets.some((t) => t.positive[0] === phrase)) return 50
  return kit.targets.some((t) => t.positive.includes(phrase)) ? 30 : 20
}

/** «да» — фраза будит какую-то цель, «нет» — только среди «Не откликаться на». */
function role(kit: TrainKit, phrase: string): string {
  return kit.targets.some((t) => t.positive.includes(phrase)) ? 'да' : 'нет'
}

type Props = { kit: TrainKit; selected: string; onSelect: (phrase: string) => void }

export default function PhraseTable({ kit, selected, onSelect }: Props) {
  const people = [...new Set(kit.phrases.flatMap((p) => Object.keys(p.people)))].sort()
  return (
    <table className="phrase-table">
      <thead>
        <tr>
          <th>Фраза</th>
          <th>Будит</th>
          {people.map((name) => (
            <th key={name}>{name}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {kit.phrases.map((p) => (
          <tr key={p.phrase} className={p.phrase === selected ? 'on' : ''} onClick={() => onSelect(p.phrase)}>
            <td>{p.phrase}</td>
            <td>{role(kit, p.phrase)}</td>
            {people.map((name) => {
              const n = p.people[name] ?? 0
              return <td key={name} className={n >= goalFor(kit, p.phrase) ? 'done' : ''}>{`${n} / ${goalFor(kit, p.phrase)}`}</td>
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
