import type { ReactNode } from 'react'
import type { CaseDetail } from '../api/models'
import { TypologyFlag } from '../components/TypologyFlag'
import { cx } from '../lib/cx'
import { leadsOf } from './rules'

/** A part of a panel, under a small printed heading. It is a landmark, so a screen reader can jump to it. */
export function Section({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={cx('flex flex-col gap-2', className)}>
      <h3 className="eyebrow">{title}</h3>
      {children}
    </section>
  )
}

/** The backend's own sentences, one per line, as they came. They can end in a whole hash, so they may break anywhere. */
export function Sentences({ items, marker = 'dash' }: { items: string[]; marker?: 'dash' | 'arrow' }) {
  return (
    <ul className="flex flex-col gap-2">
      {items.map((text, i) => (
        <li key={i} className="flex gap-2 text-sm text-fg">
          <span aria-hidden className="shrink-0 select-none text-muted">
            {marker === 'arrow' ? '→' : '–'}
          </span>
          <span className="min-w-0 [overflow-wrap:anywhere]">{text}</span>
        </li>
      ))}
    </ul>
  )
}

/** Leads from the deposit-address model: something to look into, never part of the answer. */
export function Leads({ c }: { c: CaseDetail }) {
  const leads = leadsOf(c)
  if (leads.length === 0) return null
  return (
    <Section title="Leads to check">
      <ul className="flex flex-col gap-2">
        {leads.map((flag, i) => (
          <li key={flag.wallet + i}>
            <TypologyFlag flag={flag} />
          </li>
        ))}
      </ul>
    </Section>
  )
}
