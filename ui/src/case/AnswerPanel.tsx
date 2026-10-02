import type { Candidate, CaseDetail } from '../api/models'
import { AddressChip } from '../components/AddressChip'
import { TierTag } from '../components/TierTag'
import { TypologyFlag } from '../components/TypologyFlag'
import { cx } from '../lib/cx'
import { CandidateCard } from './CandidateCard'
import { isInbound, Leads, Section, Sentences } from './parts'

/** "Sanctioned address reached", "Mixer reached", or both: from the alerts the trace raised. */
function sealHeading(c: CaseDetail): string {
  const sanctioned = c.typology_flags.some((f) => f.code === 'sanctioned_contact')
  const mixer = c.typology_flags.some((f) => f.code === 'mixer_contact')
  if (sanctioned && mixer) return 'Sanctioned address and mixer reached'
  if (mixer) return 'Mixer reached'
  if (sanctioned) return 'Sanctioned address reached'
  return 'Sanctioned or mixer reached'
}

/** An exchange that paid the wallet: context for a second request, never part of where the money went. */
function Funder({ c, candidate, onSelect }: { c: CaseDetail; candidate: Candidate; onSelect: (address: string) => void }) {
  return (
    <li className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-fg">{candidate.vasp}</span>
        <TierTag tier={candidate.label_tier} size="sm" />
        <AddressChip address={candidate.deposit_address} chain={c.chain} onSelect={() => onSelect(candidate.deposit_address)} />
      </div>
      {candidate.evidence
        .filter((e) => e.kind === 'path')
        .map((e, i) => (
          <p key={i} className="text-sm text-fg">
            {e.text}
          </p>
        ))}
    </li>
  )
}

/** "Why this exchange?": the answer of a case that names an exchange, or that reached a
 *  sanctioned address or a mixer. The one primary action of the page lives here, under the
 *  meters it follows from. */
export function AnswerPanel({ c, onSelect, className }: { c: CaseDetail; onSelect: (address: string) => void; className?: string }) {
  const sealed = c.outcome === 'SANCTIONED_OR_MIXER_REACHED'
  const outbound = c.candidates.filter((x) => !isInbound(x))
  const funders = c.candidates.filter(isInbound)
  const top = outbound.find((x) => x.vasp === c.top_vasp) ?? (sealed ? outbound[0] : undefined)
  const others = outbound.filter((x) => x !== top)
  const alerts = c.typology_flags.filter((f) => f.severity === 'high')

  return (
    <section
      aria-labelledby="answer-title"
      className={cx('flex flex-col gap-6 rounded-md border bg-surface p-5', sealed ? 'border-seal-text' : 'border-rule', className)}
    >
      <div className="flex flex-col gap-4">
        <h2 id="answer-title" className="display text-lg text-fg">
          {sealed ? sealHeading(c) : `Why ${c.top_vasp ?? 'this exchange'}?`}
        </h2>
        {sealed && alerts.length > 0 && (
          <ul className="flex flex-col gap-2">
            {alerts.map((flag, i) => (
              <li key={flag.wallet + i}>
                <TypologyFlag flag={flag} />
              </li>
            ))}
          </ul>
        )}
        {sealed && top && <h3 className="eyebrow">Nearest exchange</h3>}
        {top && <CandidateCard c={c} candidate={top} action="primary" onSelect={onSelect} />}
        {sealed && !top && <p className="text-sm text-fg">No labelled exchange was reached, so there is no exchange to write to.</p>}
      </div>

      {others.length > 0 && (
        <Section title="Other exchanges reached">
          <ul className="flex flex-col gap-5">
            {others.map((x) => (
              <li key={x.vasp + x.deposit_address} className="border-t border-rule pt-4 first:border-t-0 first:pt-0">
                <CandidateCard c={c} candidate={x} action="secondary" onSelect={onSelect} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {funders.length > 0 && (
        <Section title="Funded the wallet">
          <ul className="flex flex-col gap-3">
            {funders.map((x) => (
              <Funder key={x.vasp + x.deposit_address} c={c} candidate={x} onSelect={onSelect} />
            ))}
          </ul>
        </Section>
      )}

      <Leads c={c} />

      {c.next_steps.length > 0 && (
        <Section title="Next steps">
          <Sentences items={c.next_steps} marker="arrow" />
        </Section>
      )}

      {c.narrative && (
        <Section title="Summary">
          <p className="text-base text-fg [overflow-wrap:anywhere]">{c.narrative}</p>
        </Section>
      )}
    </section>
  )
}
