import { useMemo, useState } from 'react'
import type { CaseDetail, Chain, GraphNode } from '../../api/models'
import { AddressChip } from '../../components/AddressChip'
import { Amount } from '../../components/Amount'
import { BridgeLeg } from '../../components/BridgeLeg'
import { Button } from '../../components/Button'
import { EmptyState } from '../../components/EmptyState'
import { TxHash } from '../../components/TxHash'
import { TypologyFlag } from '../../components/TypologyFlag'
import { CHAINS } from '../../lib/chains'
import { formatDate, formatDuration } from '../../lib/format'
import { timelineOf, type TimelineEvent } from '../../lib/timeline'

const pad = (n: number) => String(n).padStart(2, '0')
const clock = (iso: string) => {
  const d = new Date(iso)
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}

/** "12 min after funds last arrived there": how long the money sat before it moved on. */
const delay = (s: number) => (s === 0 ? 'in the same block as funds arrived' : `${formatDuration(s)} after funds last arrived`)

function Event({
  event,
  chain,
  suspect,
  nodes,
  onSelect,
}: {
  event: TimelineEvent
  chain: Chain
  suspect: string
  nodes: Map<string, GraphNode>
  onSelect: (address: string) => void
}) {
  const chip = (address: string) => {
    const label = nodes.get(address)?.label
    return (
      <AddressChip
        address={address}
        chain={chain}
        entity={label?.entity}
        tier={label?.tier}
        role={address === suspect ? 'suspect' : undefined}
        actions="copy"
        onSelect={() => onSelect(address)}
      />
    )
  }
  return (
    <li data-testid="timeline-event" className="grid grid-cols-[84px_1fr] gap-x-4 border-t border-rule py-2.5 first:border-t-0">
      <span className="tabular pt-1 font-mono text-sm text-muted">{clock(event.at)}</span>
      <div className="flex min-w-0 flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-base text-fg">
          {event.kind === 'received' && event.to === suspect && (
            <>
              <span>Received from</span>
              {chip(event.from)}
            </>
          )}
          {event.kind === 'received' && event.to !== suspect && (
            <>
              {chip(event.to)}
              <span>received from</span>
              {chip(event.from)}
            </>
          )}
          {event.kind === 'sent' && (
            <>
              <span>Sent to</span>
              {chip(event.to)}
            </>
          )}
          {event.kind === 'forwarded' && !event.bridge && (
            <>
              {chip(event.from)}
              <span>forwarded to</span>
              {chip(event.to)}
            </>
          )}
          {event.bridge && (
            <>
              {chip(event.from)}
              <span>paid out on {CHAINS[event.bridge.dest_chain ?? chain].name} to</span>
              {chip(event.to)}
            </>
          )}
          <Amount value={event.amount} asset={event.asset} className="ml-auto" />
        </div>
        <div className="flex flex-wrap items-center gap-x-3 text-sm text-muted">
          {event.afterArrivalS != null && <span>{delay(event.afterArrivalS)}</span>}
          {event.amount !== event.onChain && (
            <span>
              part of a transfer of <Amount value={event.onChain} asset={event.asset} size="sm" />
            </span>
          )}
          {!event.bridge && <TxHash hash={event.txHash} chain={chain} className="ml-auto" />}
        </div>
        {event.bridge && <BridgeLeg leg={event.bridge} />}
        {event.flags.map((flag, i) => (
          <TypologyFlag key={flag.code + i} flag={flag} />
        ))}
      </div>
    </li>
  )
}

const TIMELINE_PAGE = 150

/** The money in the order it moved: received, sent, forwarded within minutes, deposited.
 *  Times are block times, in UTC. A pattern the trace saw sits on the transfer that shows it. */
export function TimelineTab({ c, onSelect }: { c: CaseDetail; onSelect: (address: string) => void }) {
  const { days: all, unplaced } = useMemo(() => timelineOf(c), [c])
  const [limit, setLimit] = useState(TIMELINE_PAGE)
  // A large case has thousands of transfers: whole days are shown until the limit is passed.
  const total = all.reduce((n, day) => n + day.events.length, 0)
  const days: typeof all = []
  let shown = 0
  for (const day of all) {
    if (shown >= limit) break
    const events = day.events.slice(0, limit - shown)
    days.push(events.length === day.events.length ? day : { ...day, events })
    shown += events.length
  }
  if (all.length === 0)
    return <EmptyState title="No transfers were read for this wallet">The timeline fills in once a trace has found transfers.</EmptyState>
  const nodes = new Map(c.graph.nodes.map((n) => [n.id, n]))

  return (
    <div className="flex flex-col gap-5">
      <ol className="flex flex-col gap-5">
        {days.map((day) => (
          <li key={day.date}>
            <div className="mb-1 flex items-baseline gap-3 border-b border-rule-strong pb-1.5">
              <h3 className="text-base font-semibold text-fg">{formatDate(day.date)}</h3>
              {day.gapDays != null && <span className="text-sm text-muted">{day.gapDays} days later</span>}
            </div>
            <ol>
              {day.events.map((event) => (
                <Event key={event.id} event={event} chain={c.chain} suspect={c.address} nodes={nodes} onSelect={onSelect} />
              ))}
            </ol>
          </li>
        ))}
      </ol>
      {shown < total && (
        <p className="flex flex-wrap items-center gap-3 text-sm text-muted">
          <span aria-live="polite">
            Showing the first {shown.toLocaleString('en-US')} of {total.toLocaleString('en-US')} transfers
          </span>
          <Button size="sm" onClick={() => setLimit((n) => n + TIMELINE_PAGE)}>
            Show {Math.min(TIMELINE_PAGE, total - shown).toLocaleString('en-US')} more
          </Button>
        </p>
      )}
      {unplaced.length > 0 && (
        <section aria-label="Across the trail" className="flex flex-col gap-2">
          <h3 className="eyebrow">Across the trail</h3>
          {unplaced.map((flag, i) => (
            <TypologyFlag key={flag.code + i} flag={flag} />
          ))}
        </section>
      )}
    </div>
  )
}
