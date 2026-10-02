import type { CSSProperties } from 'react'
import type { Chain, Hop, Tier } from '../api/models'
import { cx } from '../lib/cx'
import { explorerName, txUrl } from '../lib/explorers'
import { formatAmount, formatDate, formatDateTime, formatDuration } from '../lib/format'
import { AddressChip } from './AddressChip'
import { Amount } from './Amount'
import { OutcomeStamp, type OutcomeStampProps } from './OutcomeStamp'
import { Tip, useTip } from './Tip'

export interface HopRailProps {
  suspect: { address: string; chain: Chain }
  /** `CaseDetail.hop_rail`: the path to the nearest named exchange, in order. */
  hops: Hop[]
  /** What the case came to; drawn as the docket stamp the rail ends in. */
  stamp: Omit<OutcomeStampProps, 'size' | 'tilt'>
  /** Owners of labelled wallets on the path, by address (from `CaseDetail.graph.nodes`). */
  labels?: Record<string, { entity: string; tier: Tier }>
  /** 'tracing' while the case is queued or running: the wallet, and a line still being drawn. */
  state?: 'tracing' | 'done'
  /** Extend the rail hop by hop (when a result has just arrived). Off under reduced motion. */
  animate?: boolean
  className?: string
}

const elapsed = (hop: Hop) =>
  hop.elapsed_s == null ? formatDate(hop.block_time) : hop.elapsed_s === 0 ? 'same block' : `${formatDuration(hop.elapsed_s)} later`

/** The ticket stub on a hop: what moved and how long it took. It is the link to the transaction. */
function Stub({ hop, chain }: { hop: Hop; chain: Chain }) {
  const tip = useTip()
  const traced = hop.traced_amount ?? hop.amount
  const partial = hop.traced_amount != null && Math.abs(hop.traced_amount - hop.amount) > 1e-9
  return (
    <span className="relative flex min-w-[112px] flex-1 items-center justify-center px-2.5">
      <span aria-hidden className="rail-line absolute inset-x-0 top-1/2 -translate-y-px border-t-2 border-fg" />
      <span
        aria-hidden
        className="absolute right-0 top-1/2 -translate-y-1/2 border-y-[5px] border-l-[7px] border-y-transparent border-l-fg"
      />
      <a
        data-testid="hop-stub"
        href={txUrl(chain, hop.tx_hash)}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Hop ${hop.index}: ${formatAmount(traced, hop.asset)}, ${elapsed(hop)}. Open the transaction on ${explorerName(chain)} (new tab)`}
        aria-describedby={tip.open ? tip.id : undefined}
        {...tip.bind}
        className="stub relative z-[1] flex flex-col items-center px-2 py-1 leading-4 hover:bg-sunk"
      >
        <Amount value={traced} asset={hop.asset} size="sm" />
        <span className="tabular whitespace-nowrap font-mono text-xs text-muted">{elapsed(hop)}</span>
      </a>
      <Tip id={tip.id} anchor={tip.anchor}>
        <span className="block break-all font-mono">{hop.tx_hash}</span>
        <span className="mt-1 block text-muted">
          Transaction · {formatDateTime(hop.block_time)}
          {partial && (
            <>
              <br />
              {formatAmount(traced, hop.asset)} of a transfer of {formatAmount(hop.amount, hop.asset)} is this wallet’s money
            </>
          )}
        </span>
      </Tip>
    </span>
  )
}

/** The signature of a case: suspect wallet, hop, hop, and the docket stamp it ends in.
 *
 *  `suspect ──[ 48,500 USDT · 14 Sep ]──▶ hop ──[ 41,200 USDT · 7 min later ]──▶ deposit ── [ OKX ]`
 *
 *  When a trace has just finished, pass `animate`: the rail extends hop by hop and the stamp
 *  lands last. It is the one orchestrated animation in the app. */
export function HopRail({ suspect, hops, stamp, labels = {}, state = 'done', animate = false, className }: HopRailProps) {
  const moving = animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const step = (i: number, kind: 'rail-step' | 'rail-stamp' = 'rail-step') =>
    moving ? { className: kind, style: { '--step': i } as CSSProperties } : {}
  const abstained = stamp.outcome === 'INSUFFICIENT_EVIDENCE'

  return (
    <div className={cx('overflow-x-auto rounded-md border border-rule bg-surface', className)}>
      <ol aria-label="Path of the funds" className="flex w-full min-w-max items-center px-4 py-5">
        <li {...step(0)}>
          <AddressChip address={suspect.address} chain={suspect.chain} role="suspect" head={4} tail={4} actions="copy" />
        </li>

        {state === 'done' &&
          hops.map((hop, i) => {
            const s = step(i + 1)
            return (
              <li key={hop.tx_hash + hop.to_address} {...s} className={cx('flex flex-1 items-center', s.className)}>
                <Stub hop={hop} chain={suspect.chain} />
                <AddressChip
                  address={hop.to_address}
                  chain={suspect.chain}
                  entity={labels[hop.to_address]?.entity}
                  tier={labels[hop.to_address]?.tier}
                  head={4}
                  tail={4}
                  actions="copy"
                />
              </li>
            )
          })}

        {state === 'tracing' ? (
          <li className="flex flex-1 items-center gap-3 pl-3">
            <span aria-hidden className="rail-tracing h-0.5 min-w-[96px] flex-1" />
            <span role="status" className="whitespace-nowrap text-sm font-medium text-muted">
              Tracing…
            </span>
          </li>
        ) : (
          (() => {
            const s = step(hops.length + 1, 'rail-stamp')
            return (
              <li {...s} className={cx('flex items-center py-1 pl-0', s.className)}>
                <span
                  aria-hidden
                  className={cx('w-7 shrink-0 border-t-2', abstained ? 'border-dashed border-rule-strong' : 'border-fg')}
                />
                <OutcomeStamp {...stamp} size="lg" tilt />
              </li>
            )
          })()
        )}
      </ol>
    </div>
  )
}
