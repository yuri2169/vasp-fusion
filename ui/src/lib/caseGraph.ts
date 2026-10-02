/** What the case page draws from a `CaseDetail.graph`: one node per wallet (or per exchange,
 *  when its wallets are grouped), one edge per pair of wallets, and a place for each.
 *
 *  The layout is ours, not a library's: a column per hop (funders to the left of the wallet
 *  the case is about), and the path the Hop Rail shows kept on the first line, so the graph
 *  reads as the rail with its side branches hanging under it. Same case, same picture. */
import type { CaseDetail, GraphEdge, GraphNode, LabelOut, Tier } from '../api/models'

export type Role = GraphNode['role']

export interface FlowNode {
  /** The address, or `cluster:<name>` for the grouped wallets of one exchange. */
  id: string
  kind: 'wallet' | 'cluster'
  role: Role
  /** 0 = the wallet the case is about, 1.. = hops out, -1.. = funders. */
  column: number
  /** 0 = the main path's line. */
  row: number
  /** On the path the Hop Rail shows. */
  onPath: boolean
  /** Only ever paid the wallet the case is about. */
  funder: boolean
  label: LabelOut | null
  entity: string | null
  tier: Tier | null
  /** A wallet of the exchange the case names. */
  named: boolean
  /** The addresses in a group; the wallet itself otherwise. */
  members: string[]
  /** Traced amounts in and out, in the case's asset. */
  received: number
  sent: number
}

export interface FlowEdge {
  /** `${source}>${target}` */
  id: string
  source: string
  target: string
  direction: 'outbound' | 'inbound'
  /** The traced parts of every transfer between the two, added up. */
  amount: number
  /** In time order. */
  transfers: GraphEdge[]
  onPath: boolean
}

export interface FlowView {
  nodes: FlowNode[]
  edges: FlowEdge[]
  maxAmount: number
  asset: string
}

const COLUMN_GAP = 210
const ROW_GAP = 92

/** The part of a transfer that is the suspect wallet's money (the whole of it when the trace did not split it). */
export const traced = (e: { amount: number; traced_amount?: number | null }): number => e.traced_amount ?? e.amount

const byTime = (a: GraphEdge, b: GraphEdge) => a.block_time.localeCompare(b.block_time) || a.id.localeCompare(b.id)
const isInbound = (e: GraphEdge) => e.direction === 'inbound'

/** The path the Hop Rail shows, from the suspect wallet to the nearest exchange reached. */
export function mainPath(c: CaseDetail): string[] {
  if (c.hop_rail.length > 0) return [c.hop_rail[0].from_address, ...c.hop_rail.map((h) => h.to_address)]
  const top = c.candidates.find((x) => x.vasp === c.top_vasp && x.direction !== 'inbound')
  return top && top.path.length > 0 ? top.path : [c.address]
}

/** Whether "Group exchange wallets" would change anything: some exchange has two or more wallets here. */
export function clusterable(c: CaseDetail): boolean {
  const sizes = new Map<string, number>()
  for (const n of c.graph.nodes) if (n.cluster && n.id !== c.address) sizes.set(n.cluster, (sizes.get(n.cluster) ?? 0) + 1)
  return [...sizes.values()].some((n) => n > 1)
}

export function buildFlow(c: CaseDetail, opts: { collapse?: boolean } = {}): FlowView {
  const raw = c.graph.nodes
  const edges = c.graph.edges
  const suspect = c.address

  // --- which wallets are funders, and each wallet's column -----------------
  const paidOutbound = new Set(edges.filter((e) => !isInbound(e)).map((e) => e.target))
  const paysInbound = new Set(edges.filter(isInbound).map((e) => e.source))
  const isFunder = (n: GraphNode) => n.id !== suspect && paysInbound.has(n.id) && !paidOutbound.has(n.id)
  const columnOf = (n: GraphNode) => (n.id === suspect ? 0 : isFunder(n) ? -Math.max(1, n.hop) : Math.max(1, n.hop))

  // --- grouping: the wallets of one exchange become one node ---------------
  const groupSize = new Map<string, number>()
  for (const n of raw) if (n.cluster && n.id !== suspect) groupSize.set(n.cluster, (groupSize.get(n.cluster) ?? 0) + 1)
  const idOf = new Map<string, string>()
  for (const n of raw)
    idOf.set(n.id, opts.collapse && n.cluster && n.id !== suspect && groupSize.get(n.cluster)! > 1 ? `cluster:${n.cluster}` : n.id)

  const named = (n: GraphNode) => c.outcome === 'ATTRIBUTED' && !!c.top_vasp && n.id !== suspect && (n.cluster ?? n.label?.entity) === c.top_vasp

  const nodes = new Map<string, FlowNode>()
  for (const n of raw) {
    const id = idOf.get(n.id)!
    const column = columnOf(n)
    const seen = nodes.get(id)
    if (!seen) {
      nodes.set(id, {
        id,
        kind: id === n.id ? 'wallet' : 'cluster',
        role: n.role,
        column,
        row: 0,
        onPath: false,
        funder: isFunder(n),
        label: n.label ?? null,
        entity: id === n.id ? (n.label?.entity ?? null) : n.cluster!,
        tier: n.label?.tier ?? null,
        named: named(n),
        members: [n.id],
        received: 0,
        sent: 0,
      })
      continue
    }
    // A group stands where its nearest wallet on the way out stands, and looks like it.
    seen.members.push(n.id)
    seen.named ||= named(n)
    const nearer = seen.funder ? !isFunder(n) || column > seen.column : !isFunder(n) && column < seen.column
    if (nearer) Object.assign(seen, { role: n.role, column, funder: isFunder(n), label: n.label ?? null, tier: n.label?.tier ?? null })
  }

  // --- edges: every transfer between the same two nodes is one edge --------
  const flowEdges = new Map<string, FlowEdge>()
  for (const e of [...edges].sort(byTime)) {
    const source = idOf.get(e.source)
    const target = idOf.get(e.target)
    if (!source || !target || source === target) continue
    const id = `${source}>${target}`
    const edge = flowEdges.get(id) ?? { id, source, target, direction: isInbound(e) ? 'inbound' : 'outbound', amount: 0, transfers: [], onPath: false }
    edge.amount += traced(e)
    edge.transfers.push(e)
    flowEdges.set(id, edge)
    nodes.get(source)!.sent += traced(e)
    nodes.get(target)!.received += traced(e)
  }

  // --- the main path -------------------------------------------------------
  const path = mainPath(c)
    .map((a) => idOf.get(a))
    .filter((id, i, all): id is string => !!id && id !== all[i - 1])
  for (const id of path) nodes.get(id)!.onPath = true
  for (let i = 0; i + 1 < path.length; i++) {
    const edge = flowEdges.get(`${path[i]}>${path[i + 1]}`)
    if (edge) edge.onPath = true
  }

  // --- rows: the path on line 0, the rest under it, each near what pays it --
  const columns = new Map<number, FlowNode[]>()
  for (const n of nodes.values()) columns.set(n.column, [...(columns.get(n.column) ?? []), n])
  const sourcesOf = new Map<string, string[]>()
  for (const e of flowEdges.values()) if (e.direction === 'outbound') sourcesOf.set(e.target, [...(sourcesOf.get(e.target) ?? []), e.source])
  const placed = new Set<string>()
  const meanSourceRow = (n: FlowNode) => {
    const rows = (sourcesOf.get(n.id) ?? []).filter((id) => placed.has(id)).map((id) => nodes.get(id)!.row)
    return rows.length ? rows.reduce((a, b) => a + b, 0) / rows.length : Number.POSITIVE_INFINITY
  }
  for (const column of [...columns.keys()].sort((a, b) => a - b)) {
    const inColumn = columns.get(column)!
    const weight = (n: FlowNode) => (n.funder ? n.sent : n.received)
    const rest = inColumn
      .filter((n) => !n.onPath)
      .map((n) => ({ n, near: meanSourceRow(n) }))
      .sort((a, b) => a.near - b.near || weight(b.n) - weight(a.n) || a.n.id.localeCompare(b.n.id))
    // Line 0 belongs to the path in every column from the suspect wallet outwards.
    const first = column >= 0 && (column > 0 || inColumn.some((n) => n.onPath)) ? 1 : 0
    rest.forEach(({ n }, i) => (n.row = first + i))
    for (const n of inColumn) placed.add(n.id)
  }

  const view = [...flowEdges.values()]
  return {
    nodes: [...nodes.values()],
    edges: view,
    maxAmount: view.reduce((max, e) => Math.max(max, e.amount), 0),
    asset: c.asset ?? edges[0]?.asset ?? '',
  }
}

/** The wallets and transfers between the suspect wallet and one wallet: the fewest hops,
 *  and among those the route that carried the most. For a funder, the payment into the wallet. */
export function pathTo(view: FlowView, id: string): { nodes: Set<string>; edges: Set<string> } {
  const none = { nodes: new Set<string>(), edges: new Set<string>() }
  const target = view.nodes.find((n) => n.id === id)
  const suspect = view.nodes.find((n) => n.column === 0)
  if (!target || !suspect) return none
  if (target.id === suspect.id) return { nodes: new Set([suspect.id]), edges: new Set() }

  // Breadth-first along the direction money moved; the heaviest edges are tried first.
  const walk = (from: string, to: string, direction: 'outbound' | 'inbound') => {
    const out = new Map<string, FlowEdge[]>()
    for (const e of view.edges) if (e.direction === direction) out.set(e.source, [...(out.get(e.source) ?? []), e])
    for (const list of out.values()) list.sort((a, b) => b.amount - a.amount)
    const cameBy = new Map<string, FlowEdge>()
    const queue = [from]
    const seen = new Set(queue)
    while (queue.length) {
      const at = queue.shift()!
      if (at === to) break
      for (const e of out.get(at) ?? []) {
        if (seen.has(e.target)) continue
        seen.add(e.target)
        cameBy.set(e.target, e)
        queue.push(e.target)
      }
    }
    if (!cameBy.has(to)) return null
    const chain: FlowEdge[] = []
    for (let at = to; at !== from; at = cameBy.get(at)!.source) chain.unshift(cameBy.get(at)!)
    return chain
  }

  const chain = walk(suspect.id, target.id, 'outbound') ?? walk(target.id, suspect.id, 'inbound')
  if (!chain) return { nodes: new Set([target.id]), edges: new Set() }
  return { nodes: new Set([chain[0].source, ...chain.map((e) => e.target)]), edges: new Set(chain.map((e) => e.id)) }
}

export function nodeXY(n: Pick<FlowNode, 'column' | 'row'>): { x: number; y: number } {
  return { x: n.column * COLUMN_GAP, y: n.row * ROW_GAP }
}

/** Edge width in pixels: 1.5 for nothing, 10 for the largest flow, by the square root (so area, not length, reads as amount). */
export function edgeWidth(amount: number, max: number): number {
  if (max <= 0 || amount <= 0) return 1.5
  return Math.round((1.5 + 8.5 * Math.sqrt(Math.min(1, amount / max))) * 10) / 10
}

/** What came into and went out of one wallet on this trail, in time order. */
export function ledgerOf(c: CaseDetail, address: string) {
  const incoming = c.graph.edges.filter((e) => e.target === address).sort(byTime)
  const outgoing = c.graph.edges.filter((e) => e.source === address).sort(byTime)
  const sum = (list: GraphEdge[]) => list.reduce((total, e) => total + traced(e), 0)
  return { incoming, outgoing, received: sum(incoming), sent: sum(outgoing) }
}
