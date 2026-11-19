// «Может передавать:» — строка на каждого другого исполнителя: флажок связи и
// условие «Когда вызывать» (Enter или потеря фокуса — сохранить).
import { useState } from 'react'
import type { ExecutorItem, LinkItem } from '../../schema/blocks'

/** enabled — связь есть; when — условие передачи. */
type OnLink = (to: string, enabled: boolean, when: string) => void

/** noTools — модель не умеет передавать: связь можно только убрать, не добавить и не править. */
type RowProps = { target: ExecutorItem; link: LinkItem | undefined; disabled: boolean; noTools: boolean; onLink: OnLink }

/**
 * Строка связи. Условие, введённое у выключенной связи, включает её:
 * иначе пришлось бы сначала ставить флажок, ждать применения и только потом писать.
 */
function LinkRow({ target, link, disabled, noTools, onLink }: RowProps) {
  const name = target.name || target.id
  const saved = link?.when ?? ''
  const [draft, setDraft] = useState(saved)
  const save = () => {
    const when = draft.trim()
    if (when === saved.trim() || (!link && !when)) setDraft(saved)
    else onLink(target.id, true, when)
  }
  return (
    <div role="group" aria-label={name} className="link-row">
      <label className="link-head">
        <input type="checkbox" className="switch" checked={!!link} disabled={disabled || (noTools && !link)} onChange={(e) => onLink(target.id, e.target.checked, draft.trim())} />
        <span className="link-name">{name}</span>
      </label>
      <input
        className="val link-when"
        aria-label="Когда вызывать"
        value={draft}
        placeholder={target.description || 'Когда вызывать'}
        disabled={disabled || noTools}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        onBlur={save}
      />
      {link && !link.active && <div className="set-note warn">неактивна — укажите, когда вызывать</div>}
      {!link && !disabled && !noTools && <div className="set-fine link-hint">ввод условия включит связь</div>}
    </div>
  )
}

type Props = {
  executor: ExecutorItem
  /** Все исполнители, кроме самого executor. */
  others: ExecutorItem[]
  disabled: boolean
  /** Модель исполнителя не умеет инструменты: передавать не сможет. */
  noTools: boolean
  onLink: OnLink
}

export default function LinkRows({ executor, others, disabled, noTools, onLink }: Props) {
  return (
    <div className="field field-block">
      <span className="cap">Может передавать:</span>
      {noTools && <div className="set-note warn">эта модель не умеет передавать задачи</div>}
      {others.length === 0 && <div className="set-note">Других исполнителей пока нет</div>}
      {others.map((t) => {
        const link = executor.links.find((l) => l.to === t.id)
        // key: черновик условия сбрасывается, когда связь изменилась в настройках
        const key = `${t.id}:${link ? 'on' : 'off'}:${link?.when ?? ''}`
        return <LinkRow key={key} target={t} link={link} disabled={disabled} noTools={noTools} onLink={onLink} />
      })}
    </div>
  )
}
