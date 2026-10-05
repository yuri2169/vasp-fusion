/** The Timeline tab's data: every transfer of a case in the order it happened, with how long
 *  the money sat before it moved on, and the patterns the trace saw on the transfer that shows them. */
import type { CaseDetail, Crossing, GraphEdge, TypologyFlag } from '../api/models'
import { traced } from './caseGraph'

export interface TimelineEvent {
  id: string
  /** ISO time of the block, UTC. */
  at: string
  /** received: money came towards the wallet; sent: the wallet paid it out; forwarded: a later wallet passed it on. */
  kind: 'received' | 'sent' | 'forwarded'
  from: string
  to: string
  /** The suspect wallet's part of the transfer, and the whole transfer as the chain records it. */
  amount: number
  onChain: number
  asset: string
  txHash: string
  /** sent and forwarded: seconds since money last arrived at `from` on this trail; null when none was seen arriving. */
  afterArrivalS: number | null
  flags: TypologyFlag[]
  /** Set when the transfer is a bridge's payout on another chain. */
  bridge?: Crossing
}

export interface TimelineDay {
  /** YYYY-MM-DD, UTC. */
  date: string
  /** Whole days since the day before it in the list, when two or more. */
  gapDays: number | null
  events: TimelineEvent[]
}

const DAY_MS = 86_400_000
const seconds = (iso: string) => Math.round(Date.parse(iso) / 1000)

export function timelineOf(c: CaseDetail): { days: TimelineDay[]; unplaced: TypologyFlag[] } {
  const edges = [...c.graph.edges].sort((a, b) => a.block_time.localeCompare(b.block_time) || a.id.localeCompare(b.id))

  const lastArrivalBefore = (wallet: string, edge: GraphEdge): number | null => {
    let latest: number | null = null
    for (const e of edges) {
      if (e === edge || e.target !== wallet || e.block_time > edge.block_time) continue
      latest = Math.max(latest ?? 0, seconds(e.block_time))
    }
    return latest === null ? null : seconds(edge.block_time) - latest
  }

  const events: TimelineEvent[] = edges.map((e) => {
    const kind = e.direction === 'inbound' ? 'received' : e.source === c.address ? 'sent' : 'forwarded'
    return {
      id: e.id,
      at: e.block_time,
      kind,
      from: e.source,
      to: e.target,
      amount: traced(e),
      onChain: e.amount,
      asset: e.asset,
      txHash: e.tx_hash,
      ...(e.bridge ? { bridge: e.bridge } : {}),
      afterArrivalS: kind === 'received' ? null : lastArrivalBefore(e.source, e),
      flags: [],
    }
  })

  const unplaced: TypologyFlag[] = []
  for (const flag of c.typology_flags) {
    const event = events.find((e) => flag.tx_hashes.includes(e.txHash))
    if (event) event.flags.push(flag)
    else unplaced.push(flag)
  }

  const days: TimelineDay[] = []
  for (const event of events) {
    const date = event.at.slice(0, 10)
    const last = days.at(-1)
    if (last?.date === date) {
      last.events.push(event)
      continue
    }
    const gap = last ? Math.round((Date.parse(date) - Date.parse(last.date)) / DAY_MS) : 0
    days.push({ date, gapDays: gap >= 2 ? gap : null, events: [event] })
  }
  return { days, unplaced }
}
