/** What the case page draws from a `CaseDetail.graph`: one node per wallet (or per exchange,
 *  when its wallets are grouped), one edge per pair of wallets, and a place for each.
 *
 *  The layout is ours, not a library's: a column per hop (funders to the left of the wallet
 *  the case is about), and the path the Hop Rail shows kept on the first line, so the graph
 *  reads as the rail with its side branches hanging under it. Same case, same picture. */
import type { CaseDetail, Crossing, GraphEdge, GraphNode, LabelOut, Tier } from '../api/models'
import { walletId } from './chains'

export type Role = GraphNode['role']

export interface FlowNode {
  /** The address, `cluster:<name>` for the grouped wallets of one exchange, `more:<column>`
   *  for the wallets of one hop that a large graph does not draw one by one (foldFlow), or
   *  `fan:<in|out>:<wallet>` for the many small wallets that paid one wallet (or were paid by it). */
  id: string
  kind: 'wallet' | 'cluster' | 'more' | 'fan'
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
  /** A fan node: which way its wallets' money went, and the wallet they share. */
  fan?: { side: FanSide; of: string }
  /** Where the layout put it, when that is not its column and row (an opened fan's grid). */
  at?: { x: number; y: number }
}

export type FanSide = 'in' | 'out'

export interface FlowEdge {
  /** `${source}>${target}` */
  id: string
  source: string
  target: string
  direction: 'outbound' | 'inbound'
  /** The traced parts of every transfer between the two, added up, in `asset`. */
  amount: number
  asset: string
  /** In time order. */
  transfers: GraphEdge[]
  onPath: boolean
  /** Set when this line is a bridge's payout: it joins two chains. */
  bridge?: Crossing
  /** One line of a fan: drawn square, along a shared trunk, so it stays off the tile's text. */
  fan?: FanSide
}

export interface FlowView {
  nodes: FlowNode[]
  edges: FlowEdge[]
  maxAmount: number
  asset: string
}

export const COLUMN_GAP = 184
export const ROW_GAP = 90

/** The part of a transfer that is the suspect wallet's money (the whole of it when the trace did not split it). */
export const traced = (e: { amount: number; traced_amount?: number | null }): number => e.traced_amount ?? e.amount

const byTime = (a: GraphEdge, b: GraphEdge) => a.block_time.localeCompare(b.block_time) || a.id.localeCompare(b.id)
const isInbound = (e: GraphEdge) => e.direction === 'inbound'

/** The path the Hop Rail shows, from the suspect wallet to the nearest exchange reached. */
export function mainPath(c: CaseDetail): string[] {
  // the rail and a candidate's path carry plain addresses with their chain beside them
  if (c.hop_rail.length > 0)
    return [walletId(c.chain, c.hop_rail[0].from_address, c.hop_rail[0].from_chain), ...c.hop_rail.map((h) => walletId(c.chain, h.to_address, h.to_chain))]
  const top = c.candidates.find((x) => x.vasp === c.top_vasp && x.direction !== 'inbound')
  return top && top.path.length > 0 ? top.path.map((a, i) => walletId(c.chain, a, top.path_chains?.[i])) : [c.address]
}

/** Whether "Group exchange wallets" would change anything: some exchange has two or more wallets here. */
export function clusterable(c: CaseDetail): boolean {
  const sizes = new Map<string, number>()
  for (const n of c.graph.nodes) if (n.cluster && n.id !== c.address) sizes.set(n.cluster, (sizes.get(n.cluster) ?? 0) + 1)
  return [...sizes.values()].some((n) => n > 1)
}

/** Of the unlabelled wallets that only paid one wallet (or were only paid by it), this many are
 *  drawn; the rest are one node until it is opened. */
export const FAN_KEEP = 4
/** An opened fan of payers is a grid: this many wallets a column, half above the line and half under. */
export const FAN_COLUMN = 10

export const fanId = (side: FanSide, of: string) => `fan:${side}:${of}`

export interface FlowOptions {
  collapse?: boolean
  /** Fans the officer opened (ids as `fanId` gives them). */
  openFans?: ReadonlySet<string>
  /** false = every wallet is its own node, whatever the fan (to find a wallet's path). */
  fans?: boolean
}

export function buildFlow(c: CaseDetail, opts: FlowOptions = {}): FlowView {
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
    const edge = flowEdges.get(id) ?? { id, source, target, direction: isInbound(e) ? 'inbound' : 'outbound', amount: 0, asset: e.asset, transfers: [], onPath: false }
    edge.amount += traced(e)
    edge.transfers.push(e)
    if (e.bridge) edge.bridge = e.bridge
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

  if (opts.fans !== false && raw.length <= BIG_GRAPH) groupFans(nodes, flowEdges, opts.openFans)

  // --- rows: the path on line 0, the rest under it, each near what pays it --
  const columns = new Map<number, FlowNode[]>()
  // Appended in place: copying the list for every wallet is quadratic in a hop's wallets.
  const into = <K, V>(map: Map<K, V[]>, key: K, value: V) => {
    const list = map.get(key)
    if (list) list.push(value)
    else map.set(key, [value])
  }
  for (const n of nodes.values()) into(columns, n.column, n)
  const sourcesOf = new Map<string, string[]>()
  for (const e of flowEdges.values()) if (e.direction === 'outbound') into(sourcesOf, e.target, e.source)
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
  placeFunders(columns)

  const view = [...flowEdges.values()]
  return {
    nodes: [...nodes.values()],
    edges: view,
    maxAmount: view.reduce((max, e) => Math.max(max, e.amount), 0),
    asset: c.asset ?? edges[0]?.asset ?? '',
  }
}

/** Fans. A wallet whose every transfer here is with one other wallet, all the same way, is a
 *  leaf of that wallet. Many leaves make a fan: their lines converge on one tile and cover its
 *  name. So the lines of a fan are marked (they are drawn along a shared trunk), and of the
 *  unlabelled leaves only the FAN_KEEP largest are drawn; the rest are one node that says how
 *  many it stands for and what they moved, until the officer opens it. A labelled wallet is
 *  never put in the group. Nothing is dropped: the group's amount is its wallets' sum. */
function groupFans(nodes: Map<string, FlowNode>, edges: Map<string, FlowEdge>, open?: ReadonlySet<string>) {
  const touching = new Map<string, FlowEdge[]>()
  for (const e of edges.values())
    for (const id of [e.source, e.target]) {
      const list = touching.get(id)
      if (list) list.push(e)
      else touching.set(id, [e])
    }
  const fans = new Map<string, { side: FanSide; of: string; leaves: FlowNode[] }>()
  for (const n of nodes.values()) {
    const mine = touching.get(n.id) ?? []
    if (n.onPath || n.column === 0 || n.kind !== 'wallet' || mine.length !== 1 || mine[0].bridge) continue
    const side: FanSide = mine[0].source === n.id ? 'in' : 'out'
    const of = side === 'in' ? mine[0].target : mine[0].source
    const id = fanId(side, of)
    const fan = fans.get(id)
    if (fan) fan.leaves.push(n)
    else fans.set(id, { side, of, leaves: [n] })
  }
  const moved = (n: FlowNode, side: FanSide) => (side === 'in' ? n.sent : n.received)
  for (const [id, { side, of, leaves }] of fans) {
    // Two payers already meet at the tile; payees spread out, so only a real fan of them is squared.
    if (side === 'in' ? leaves.length < 2 : leaves.length <= FAN_KEEP) continue
    for (const n of leaves) touching.get(n.id)![0].fan = side
    const plain = leaves.filter((n) => !n.label).sort((a, b) => moved(b, side) - moved(a, side) || a.id.localeCompare(b.id))
    if (plain.length <= FAN_KEEP || open?.has(id)) continue
    const rest = plain.slice(FAN_KEEP)
    const first = touching.get(rest[0].id)![0]
    const group: FlowEdge = { ...first, id: side === 'in' ? `${id}>${of}` : `${of}>${id}`, source: side === 'in' ? id : of, target: side === 'in' ? of : id, amount: 0, transfers: [], onPath: false, fan: side }
    for (const n of rest) {
      const e = touching.get(n.id)![0]
      group.amount += e.amount
      group.transfers.push(...e.transfers)
      edges.delete(e.id)
      nodes.delete(n.id)
    }
    group.transfers.sort(byTime)
    edges.set(group.id, group)
    nodes.set(id, {
      id,
      kind: 'fan',
      role: 'unknown',
      column: rest[0].column,
      row: 0,
      onPath: false,
      funder: rest[0].funder,
      label: null,
      entity: null,
      tier: null,
      named: false,
      members: rest.flatMap((n) => n.members),
      received: side === 'out' ? group.amount : 0,
      sent: side === 'in' ? group.amount : 0,
      fan: { side, of },
    })
  }
}

/** The wallets that paid the suspect wallet stand either side of its line, the largest nearest,
 *  and the line itself is left free: their lines then come in along it from the left and never
 *  rise through the tile's address. More than FAN_COLUMN of them (an opened fan) become a grid
 *  further to the left, and whoever funded the funders moves left to make room. */
function placeFunders(columns: Map<number, FlowNode[]>) {
  // the group of the rest stands furthest out, after the wallets that are drawn
  const payers = (columns.get(-1) ?? []).filter((n) => !n.onPath).sort((a, b) => Number(a.kind === 'fan') - Number(b.kind === 'fan') || a.row - b.row)
  if (payers.length < 2) return
  const extra = Math.ceil(payers.length / FAN_COLUMN) - 1
  payers.forEach((n, i) => {
    const k = i % FAN_COLUMN
    n.row = (k % 2 === 0 ? 1 : -1) * (Math.floor(k / 2) + 1)
    if (extra > 0) n.at = { x: -(1 + Math.floor(i / FAN_COLUMN)) * COLUMN_GAP, y: n.row * ROW_GAP }
  })
  if (extra > 0)
    for (const [column, list] of columns)
      if (column < -1) for (const n of list) n.at = { x: (column - extra) * COLUMN_GAP, y: n.row * ROW_GAP }
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
    for (const e of view.edges) {
      if (e.direction !== direction) continue
      const list = out.get(e.source)
      if (list) list.push(e)
      else out.set(e.source, [e])
    }
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

// --- a large graph: drawn in part, opened on request ---------------------------

/** Above this many wallets a graph is not drawn whole: a column of 400 wallets is 36,000 px
 *  tall and tells nobody anything. The largest wallets of each hop are drawn, the rest of the
 *  hop is one node that says how many it stands for, and hops past the answer wait to be asked for. */
export const BIG_GRAPH = 250

export interface FoldOptions {
  /** Wallets drawn per hop, besides the ones on the path. */
  perColumn: number
  /** Hops out (and funders in) that are drawn; null = all of them. */
  maxHop: number | null
  /** Wallets that must be drawn whatever their size: the one being looked at, and the path to it. */
  keep?: ReadonlySet<string>
  /** A hop the officer asked to see more of: column → wallets drawn there. */
  shown?: ReadonlyMap<number, number>
}

export interface FoldedView extends FlowView {
  /** Per hop, how many wallets its `more:` node stands for. */
  folded: { column: number; wallets: number }[]
  /** The first hop that is not drawn, and how many wallets are at or past it. */
  beyond: { hop: number; wallets: number } | null
}

/** A view with at most `perColumn` wallets a hop (plus the path), in the order `buildFlow` gave
 *  them. Which ones: the wallets asked for (`keep`), then the named exchange's, then any labelled
 *  wallet, then by amount. So a labelled wallet is drawn before a larger unlabelled one. No wallet
 *  is dropped: it is drawn, counted in its hop's `more:` node, or counted in `beyond`. A transfer
 *  to a folded wallet is added into the line to its `more:` node; a transfer between two wallets of
 *  one fold, or across the hop limit, is not drawn (the Transfers tab has every one). */
export function foldFlow(view: FlowView, opts: FoldOptions): FoldedView {
  const columns = new Map<number, FlowNode[]>()
  let beyond = 0
  for (const n of view.nodes) {
    if (opts.maxHop != null && Math.abs(n.column) > opts.maxHop) {
      beyond += n.members.length
      continue
    }
    const list = columns.get(n.column)
    if (list) list.push(n)
    else columns.set(n.column, [n])
  }

  const rank = (n: FlowNode) => (opts.keep?.has(n.id) ? 3 : n.named ? 2 : n.label ? 1 : 0)
  const weight = (n: FlowNode) => (n.funder ? n.sent : n.received)
  const nodes: FlowNode[] = []
  const standsFor = new Map<string, string>()
  const folded: FoldedView['folded'] = []

  for (const column of [...columns.keys()].sort((a, b) => a - b)) {
    const all = columns.get(column)!.sort((a, b) => a.row - b.row)
    const rest = all.filter((n) => !n.onPath && n.column !== 0)
    // Wallets that are kept for a selection are drawn besides the hop's own number, so looking
    // at one wallet never pushes another into the fold.
    const limit = (opts.shown?.get(column) ?? opts.perColumn) + rest.filter((n) => rank(n) === 3).length
    for (const n of all) if (n.onPath || n.column === 0) nodes.push(n), standsFor.set(n.id, n.id)
    if (rest.length <= limit) {
      for (const n of rest) nodes.push(n), standsFor.set(n.id, n.id)
      continue
    }
    const drawn = new Set([...rest].sort((a, b) => rank(b) - rank(a) || weight(b) - weight(a) || a.id.localeCompare(b.id)).slice(0, limit))
    const firstRow = rest[0].row
    const hidden = rest.filter((n) => !drawn.has(n))
    rest.filter((n) => drawn.has(n)).forEach((n, i) => {
      nodes.push({ ...n, row: firstRow + i })
      standsFor.set(n.id, n.id)
    })
    const id = `more:${column}`
    for (const n of hidden) standsFor.set(n.id, id)
    nodes.push({
      id,
      kind: 'more',
      role: 'unknown',
      column,
      row: firstRow + drawn.size,
      onPath: false,
      funder: column < 0,
      label: null,
      entity: null,
      tier: null,
      named: false,
      members: hidden.flatMap((n) => n.members),
      received: hidden.reduce((sum, n) => sum + n.received, 0),
      sent: hidden.reduce((sum, n) => sum + n.sent, 0),
    })
    folded.push({ column, wallets: hidden.reduce((sum, n) => sum + n.members.length, 0) })
  }

  const edges = new Map<string, FlowEdge>()
  for (const e of view.edges) {
    const source = standsFor.get(e.source)
    const target = standsFor.get(e.target)
    if (!source || !target) continue // one end is past the hop limit
    if (source === target) continue // both ends are in the same fold: nothing to draw between them
    if (source === e.source && target === e.target) {
      edges.set(e.id, e)
      continue
    }
    const id = `${source}>${target}`
    const sum = edges.get(id)
    if (sum) {
      sum.amount += e.amount
      sum.transfers.push(...e.transfers)
    } else edges.set(id, { ...e, id, source, target, onPath: false, transfers: [...e.transfers] })
  }

  const drawnEdges = [...edges.values()]
  const hops = view.nodes.reduce((max, n) => Math.max(max, Math.abs(n.column)), 0)
  return {
    nodes,
    edges: drawnEdges,
    maxAmount: drawnEdges.reduce((max, e) => Math.max(max, e.amount), 0),
    asset: view.asset,
    folded,
    beyond: beyond > 0 && opts.maxHop != null && opts.maxHop < hops ? { hop: opts.maxHop + 1, wallets: beyond } : null,
  }
}

/** What stays in view when one wallet is looked at: the path to it. Everything else steps back.
 *  null = nothing steps back: no selection, an unknown wallet, or the suspect wallet itself
 *  (every transfer in the case is its own). */
export function focusOf(view: FlowView, id: string | null): { nodes: Set<string>; edges: Set<string> } | null {
  if (!id) return null
  const node = view.nodes.find((n) => n.id === id)
  if (!node || node.column === 0) return null
  return pathTo(view, id)
}

export function nodeXY(n: Pick<FlowNode, 'column' | 'row' | 'at'>): { x: number; y: number } {
  return n.at ? { ...n.at } : { x: n.column * COLUMN_GAP, y: n.row * ROW_GAP }
}

/** Edge width in pixels: 1.5 for nothing, 8 for the largest flow, by the square root (a
 *  linear scale would draw every small transfer as a hairline beside one large one). */
export function edgeWidth(amount: number, max: number): number {
  if (max <= 0 || amount <= 0) return 1.5
  return Math.round((1.5 + 6.5 * Math.sqrt(Math.min(1, amount / max))) * 10) / 10
}

/** What came into and went out of one wallet on this trail, in time order. */
export function ledgerOf(c: CaseDetail, address: string) {
  const incoming = c.graph.edges.filter((e) => e.target === address).sort(byTime)
  const outgoing = c.graph.edges.filter((e) => e.source === address).sort(byTime)
  const sum = (list: GraphEdge[]) => list.reduce((total, e) => total + traced(e), 0)
  return { incoming, outgoing, received: sum(incoming), sent: sum(outgoing) }
}
