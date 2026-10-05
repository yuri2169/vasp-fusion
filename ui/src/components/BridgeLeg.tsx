import { ArrowRight } from 'lucide-react'
import type { Crossing } from '../api/models'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatAmount, formatDuration } from '../lib/format'
import { ChainBadge } from './ChainBadge'
import { TxHash } from './TxHash'

/** From one chain to another: two badges and an arrow. */
export function ChainHop({ from, to, name, size = 'sm' }: { from: Crossing['source_chain']; to: Crossing['dest_chain']; name?: string | null; size?: 'sm' | 'md' }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1" aria-label={`${CHAINS[from].name} to ${to ? CHAINS[to].name : (name ?? 'another chain')}`}>
      <ChainBadge chain={from} size={size} />
      <ArrowRight size={12} aria-hidden className="text-ink-dim" />
      {to ? <ChainBadge chain={to} size={size} /> : <span className="border border-dashed border-rule px-1 font-mono text-2xs text-ink-dim">{name ?? '?'}</span>}
    </span>
  )
}

const took = (s: number | null | undefined) => (s == null ? null : s === 0 ? 'in the same second' : `${formatDuration(s)} later`)

/** A bridge leg in full: the bridge, both chains, what went in and what came out, and the
 *  two transactions, each a link to its own chain's explorer. `status` other than followed
 *  says why the trail stops there, in the backend's words. */
export function BridgeLeg({ leg, className }: { leg: Crossing; className?: string }) {
  return (
    <div data-testid="bridge-leg" className={cx('flex flex-col gap-1 border-l-2 border-network pl-2.5 text-sm text-fg', className)}>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">{leg.bridge} bridge</span>
        <ChainHop from={leg.source_chain} to={leg.dest_chain} name={leg.dest_name} />
        {leg.status === 'followed' && leg.amount_out != null && (
          <span className="tabular font-mono text-muted">
            {formatAmount(leg.amount_in, leg.asset_in)} in · {formatAmount(leg.amount_out, leg.asset_out ?? '')} out
            {took(leg.seconds) && ` · ${took(leg.seconds)}`}
          </span>
        )}
        {leg.status !== 'followed' && <span className="border border-dashed border-rule px-1 text-muted">{leg.status === 'unresolved' ? 'Not matched' : 'Matched, not followed'}</span>}
      </p>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-muted">
        <span className="inline-flex items-center gap-1">
          Deposit <TxHash hash={leg.source_tx} chain={leg.source_chain} />
        </span>
        {leg.payout_tx && leg.dest_chain && (
          <span className="inline-flex items-center gap-1">
            Payout <TxHash hash={leg.payout_tx} chain={leg.dest_chain} />
          </span>
        )}
        {leg.payout_tx && !leg.dest_chain && <span className="break-all font-mono">Payout {leg.payout_tx}</span>}
      </p>
      {leg.reason && <p className="text-muted">Not followed: {leg.reason}.</p>}
      {leg.status === 'followed' && leg.matched_by && (
        <p className="text-muted">
          Matched by the bridge’s own index ({leg.matched_by}); the amount out is read on {leg.dest_chain ? CHAINS[leg.dest_chain].name : leg.dest_name}
          {leg.fee != null && leg.fee > 0 && `. The crossing cost ${formatAmount(leg.fee, leg.asset_in)}`}.
        </p>
      )}
    </div>
  )
}
