import type { CaseDetail } from '../api/models'
import { cx } from '../lib/cx'
import { CandidateCard } from './CandidateCard'
import { Leads, Section, Sentences } from './parts'
import { isInbound } from './rules'

/** INSUFFICIENT EVIDENCE is an answer, not an error: no exchange is named, and the panel
 *  says why, what was reached, what would change it, and what to do next. Slate and dashed,
 *  like its stamp; nothing on this screen is saffron. */
export function AbstainPanel({ c, onSelect, className }: { c: CaseDetail; onSelect: (address: string) => void; className?: string }) {
  const reached = c.candidates.filter((x) => !isInbound(x))
  const changes = c.what_would_change ?? []
  const steps = c.next_steps ?? []

  return (
    <section
      aria-labelledby="answer-title"
      className={cx('flex flex-col gap-6 border border-dashed border-ink bg-surface p-4', className)}
    >
      <div className="flex flex-col gap-3">
        <p className="eyebrow">Insufficient evidence</p>
        <h2 id="answer-title" className="title text-lg text-fg">
          No exchange is named
        </h2>
        {c.abstain_reason && <p className="text-md text-fg [overflow-wrap:anywhere]">{c.abstain_reason}</p>}
        <p className="text-sm text-muted">
          The tool names an exchange only when the evidence clears the bar. This is a result to act on, not a failed trace.
        </p>
      </div>

      {reached.length > 0 && (
        <Section title="What was reached">
          <ul className="flex flex-col gap-5">
            {reached.map((x) => (
              <li key={x.vasp + x.deposit_address} className="border-t border-rule pt-4 first:border-t-0 first:pt-0">
                <CandidateCard c={c} candidate={x} onSelect={onSelect} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {changes.length > 0 && (
        <Section title="What would change this">
          <Sentences items={changes} />
        </Section>
      )}

      {steps.length > 0 && (
        <Section title="Next steps">
          <Sentences items={steps} marker="arrow" />
        </Section>
      )}

      <Leads c={c} />

      {c.narrative && (
        <Section title="Summary">
          <p className="text-md text-fg [overflow-wrap:anywhere]">{c.narrative}</p>
        </Section>
      )}
    </section>
  )
}
