import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
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
  /** While tracing: how many hops out the trace has gone so far (`CaseDetail.progress.hop`). */
  depth?: number
  /** Extend the rail hop by hop (when a result has just arrived). Off under reduced motion. */
  animate?: boolean
  /** The wallet being shown elsewhere on the page (the graph, the side panel). */
  selected?: string | null
  /** The wallets on the path to it. */
  marked?: ReadonlySet<string>
  /** Makes every wallet on the rail a button that shows it. */
  onSelect?: (address: string) => void
  /** Sits under the path, inside the rail's card (where the funds went). */
  footer?: ReactNode
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
    <span className="relative flex min-w-[108px] flex-1 items-center justify-center px-2">
      <span aria-hidden className="rail-line absolute inset-x-0 top-1/2 border-t border-chain" />
      <span
        aria-hidden
        className="absolute right-0 top-1/2 h-[5px] w-[5px] -translate-y-1/2 bg-chain"
      />
      <a
        data-testid="hop-stub"
        href={txUrl(chain, hop.tx_hash)}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Hop ${hop.index}: ${formatAmount(traced, hop.asset)}, ${elapsed(hop)}. Open the transaction on ${explorerName(chain)} (new tab)`}
        aria-describedby={tip.open ? tip.id : undefined}
        {...tip.bind}
        className="stub relative z-[1] flex flex-col items-center px-2 py-0.5 transition-colors duration-150 hover:bg-chain-wash"
      >
        <Amount value={traced} asset={hop.asset} size="sm" />
        <span className="tabular whitespace-nowrap font-mono text-sm text-muted">{elapsed(hop)}</span>
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
export function HopRail({
  suspect,
  hops,
  stamp,
  labels = {},
  state = 'done',
  depth = 0,
  animate = false,
  selected,
  marked,
  onSelect,
  footer,
  className,
}: HopRailProps) {
  const pick = (address: string) => ({
    selected: selected === address,
    marked: marked?.has(address),
    onSelect: onSelect && (() => onSelect(address)),
  })
  const moving = animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const step = (i: number, kind: 'rail-step' | 'rail-stamp' = 'rail-step') =>
    moving ? { className: kind, style: { '--step': i } as CSSProperties } : {}
  const abstained = stamp.outcome === 'INSUFFICIENT_EVIDENCE'

  // A long path scrolls sideways under the stamp, which stays in view: the answer is never off-screen.
  const scroller = useRef<HTMLDivElement>(null)
  const [overflowing, setOverflowing] = useState(false)
  useEffect(() => {
    const el = scroller.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const measure = () => setOverflowing(el.scrollWidth > el.clientWidth + 1)
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    measure()
    return () => observer.disconnect()
  }, [hops.length, state])

  return (
    <div className={cx('panel', className)}>
     <div ref={scroller} className="overflow-x-auto">
      <ol aria-label="Path of the funds" className="flex w-full min-w-max items-stretch pl-4">
        <li {...step(0)} className={cx('flex items-center py-5', step(0).className)}>
          <AddressChip
            address={suspect.address}
            chain={suspect.chain}
            role="suspect"
            head={4}
            tail={4}
            actions="copy"
            className="shrink-0"
            {...pick(suspect.address)}
          />
        </li>

        {state === 'done' &&
          hops.map((hop, i) => {
            const s = step(i + 1)
            return (
              <li key={hop.tx_hash + hop.to_address} {...s} className={cx('flex flex-1 items-center py-5', s.className)}>
                <Stub hop={hop} chain={suspect.chain} />
                <AddressChip
                  address={hop.to_address}
                  chain={suspect.chain}
                  entity={labels[hop.to_address]?.entity}
                  tier={labels[hop.to_address]?.tier}
                  head={4}
                  tail={4}
                  actions="copy"
                  className="shrink-0"
                  {...pick(hop.to_address)}
                />
              </li>
            )
          })}

        {state === 'tracing' &&
          Array.from({ length: depth }, (_, i) => (
            <li key={i} className="flex items-center py-5">
              <span aria-hidden className="w-12 border-t border-dashed border-chain" />
              <span
                data-testid="hop-pending"
                className="tabular inline-flex h-6 items-center whitespace-nowrap border border-dashed border-chain px-2 font-mono text-sm text-chain"
              >
                hop {i + 1}
              </span>
            </li>
          ))}

        {state === 'tracing' ? (
          <li className="flex flex-1 items-center gap-3 py-5 pl-3 pr-4">
            <span aria-hidden className="rail-tracing h-px min-w-[96px] flex-1" />
            <span role="status" className="whitespace-nowrap text-sm font-medium text-chain">
              Tracing…
            </span>
          </li>
        ) : (
          (() => {
            const s = step(hops.length + 1, 'rail-stamp')
            return (
              <li
                {...s}
                className={cx(
                  'sticky right-0 z-[2] flex items-center bg-surface py-4 pr-4',
                  overflowing && 'border-l border-rule pl-3',
                  s.className,
                )}
              >
                <span
                  aria-hidden
                  className={cx('w-7 shrink-0 border-t', abstained ? 'border-dashed border-data' : stamp.outcome === 'ATTRIBUTED' ? 'border-fusion' : 'border-danger')}
                />
                <OutcomeStamp {...stamp} size="lg" tilt />
              </li>
            )
          })()
        )}
      </ol>
     </div>
      {footer && <div className="border-t border-rule px-4 py-3">{footer}</div>}
    </div>
  )
}
