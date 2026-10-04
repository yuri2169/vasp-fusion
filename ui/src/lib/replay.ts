import type { FlowView } from './caseGraph'

/** One step of the replay: the first time money moved between two wallets of the picture. */
export interface ReplayStep {
  edge: string
  source: string
  target: string
  /** Block time of the earliest transfer between the two; null when the chain gave none. */
  time: string | null
  amount: number
  asset: string
  transfers: number
}

/** The picture's edges in the order the money moved (by block time; an edge with no time
 *  goes last). The order is stable, so a replay is the same every time. */
export function replaySteps(view: FlowView): ReplayStep[] {
  const steps = view.edges.map((e) => ({
    edge: e.id,
    source: e.source,
    target: e.target,
    time: e.transfers.reduce<string | null>((first, t) => (t.block_time && (!first || t.block_time < first) ? t.block_time : first), null),
    amount: e.amount,
    asset: e.asset,
    transfers: e.transfers.length,
  }))
  return steps.sort((a, b) => (a.time && b.time ? a.time.localeCompare(b.time) : a.time ? -1 : b.time ? 1 : 0) || a.edge.localeCompare(b.edge))
}

/** What is on the picture after `at` steps: those edges, the wallets they touch, and the
 *  wallet the case is about (it is there before anything moves). */
export function shownAt(view: FlowView, steps: ReplayStep[], at: number): { nodes: Set<string>; edges: Set<string> } {
  const nodes = new Set(view.nodes.filter((n) => n.column === 0).map((n) => n.id))
  const edges = new Set<string>()
  for (const s of steps.slice(0, Math.max(0, at))) {
    edges.add(s.edge)
    nodes.add(s.source)
    nodes.add(s.target)
  }
  return { nodes, edges }
}
