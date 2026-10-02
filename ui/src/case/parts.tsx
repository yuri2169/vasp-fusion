import type { ReactNode } from 'react'
import type { Candidate, CaseDetail, TypologyFlag as Flag } from '../api/models'
import { TypologyFlag } from '../components/TypologyFlag'
import { cx } from '../lib/cx'

/** The bar a candidate must clear to be named (docs/api_contract.md; measured in B7, not calibrated). */
export const NAMING_BAR = 0.6

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

export const isLead = (flag: Flag) => flag.code === 'deposit_like'
export const leadsOf = (c: CaseDetail) => c.typology_flags.filter(isLead)

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

export const isInbound = (x: Candidate) => x.direction === 'inbound'

/** Whether a request can be drafted to this exchange from this case (the desk's own rule, B8). */
export const routable = (x: Candidate) =>
  !isInbound(x) && x.hops >= 1 && x.confidence >= NAMING_BAR && x.vasp !== 'Unidentified exchange'

export const deskLink = (c: CaseDetail, vasp: string) => `/desk?vasp=${encodeURIComponent(vasp)}&case=${encodeURIComponent(c.id)}`
