import { CircleHelp, ShieldCheck, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router'
import type { Candidate, CaseDetail } from '../api/models'
import { AddressChip } from '../components/AddressChip'
import { Amount } from '../components/Amount'
import { buttonClass } from '../components/Button'
import { DualMeter } from '../components/DualMeter'
import { EvidenceList } from '../components/EvidenceList'
import { TierTag } from '../components/TierTag'
import { cx } from '../lib/cx'
import { deskLink, isInbound, NAMING_BAR, routable } from './rules'

/** What the counterfactual check found: the label on the entry address is hidden and the
 *  wallet is traced again. A tick, a warning, or "not checked", then the backend's sentence. */
function Counterfactual({ candidate }: { candidate: Candidate }) {
  if (!candidate.counterfactual) return null
  const holds = candidate.counterfactual_holds
  const { Icon, words, tone } =
    holds === true
      ? { Icon: ShieldCheck, words: 'Holds without its strongest label', tone: 'text-verified-text' }
      : holds === false
        ? { Icon: TriangleAlert, words: 'Rests on that one label', tone: 'text-fg' }
        : { Icon: CircleHelp, words: 'Checked without its strongest label', tone: 'text-muted' }
  return (
    <div className="flex gap-2 rounded border border-rule bg-sunk px-3 py-2.5">
      <Icon size={15} aria-hidden className={cx('mt-0.5 shrink-0', tone)} />
      <div className="min-w-0">
        <p className={cx('text-xs font-semibold', tone)}>{words}</p>
        <p className="mt-0.5 text-sm text-fg [overflow-wrap:anywhere]">{candidate.counterfactual}</p>
      </div>
    </div>
  )
}

/** One exchange the trace reached: how near, how sure (two meters, never one score), what
 *  proves it, and whether it would still be named without its strongest label. */
export function CandidateCard({
  c,
  candidate,
  action = 'none',
  onSelect,
  className,
}: {
  c: CaseDetail
  candidate: Candidate
  /** 'primary': the one saffron button of the page. 'secondary': a further exchange that can be written to. */
  action?: 'primary' | 'secondary' | 'none'
  onSelect: (address: string) => void
  className?: string
}) {
  const named = candidate.confidence >= NAMING_BAR
  const scored = candidate.confidence_interval != null
  const canRequest = action !== 'none' && routable(candidate)
  const listed = candidate.evidence.filter((e) => e.kind !== 'counterfactual').length

  return (
    <article aria-label={candidate.vasp} className={cx('flex flex-col gap-3', className)}>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
        <span className="display text-lg text-fg">{candidate.vasp}</span>
        <TierTag tier={candidate.label_tier} size="sm" />
        {candidate.amount != null && c.asset && <Amount value={candidate.amount} asset={c.asset} className="ml-auto" />}
      </div>
      <AddressChip
        address={candidate.deposit_address}
        chain={c.chain}
        onSelect={() => onSelect(candidate.deposit_address)}
        className="self-start"
      />

      <DualMeter
        proximityRank={candidate.proximity_rank}
        hops={candidate.hops}
        shareOfFunds={candidate.share_of_funds}
        timeToReachS={candidate.time_to_reach_s}
        confidence={candidate.confidence}
        interval={candidate.confidence_interval}
        bar={NAMING_BAR}
      />
      <p className="text-xs text-muted">
        {scored
          ? 'The range is the deposit-address model’s. The weight of the exchange’s label, the hop decay and the share factor are rule-set.'
          : 'Rule-based, not calibrated: label weight × hop decay × share factor.'}
        {!named && ` An exchange is named at ${NAMING_BAR.toFixed(2)} or more.`}
      </p>

      {canRequest && (
        <Link to={deskLink(c, candidate.vasp)} className={buttonClass(action === 'primary' ? 'primary' : 'secondary', 'md', 'self-start')}>
          Draft request to {candidate.vasp}
        </Link>
      )}

      <Counterfactual candidate={candidate} />
      {!isInbound(candidate) &&
        (action === 'primary' ? (
          <EvidenceList items={candidate.evidence} chain={c.chain} />
        ) : (
          listed > 0 && (
            <details className="group">
              <summary className="cursor-pointer select-none text-sm font-medium text-fg underline decoration-rule-strong underline-offset-2 hover:decoration-fg">
                Evidence ({listed})
              </summary>
              <EvidenceList items={candidate.evidence} chain={c.chain} className="mt-3" />
            </details>
          )
        ))}
    </article>
  )
}
