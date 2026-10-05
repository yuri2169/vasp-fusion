/** Context beside the trail: the other transfers of the wallets a trace read
 *  (`GET /api/cases/{id}/context`), laid into a FlowView as a separate, greyed layer.
 *
 *  Context is not the suspect wallet's money. Its nodes and lines are marked `context`, and
 *  everything that reads the picture for meaning (the replay, the path to a selection, the
 *  counts, the legend's roles) leaves them out. Taking the layer away gives back the view it
 *  was added to, untouched: the default picture never changes. */
import type { CaseContext, ContextEdge, ContextNode } from '../api/models'
import { COLUMN_GAP, nodeXY, type FanSide, type FlowEdge, type FlowNode, type FlowView } from './caseGraph'

/** Other wallets drawn for one wallet, each way, before the rest become one node. */
export const CONTEXT_KEEP = 8
/** How many more one click on that node draws. */
export const CONTEXT_MORE = 50
/** The band under the picture: context tiles in rows of BAND_ACROSS, this far apart. */
const BAND_ROW = 30
const BAND_STEP = 34
const BAND_ACROSS = 5

export const contextMoreId = (side: FanSide, of: string) => `ctxmore:${side}:${of}`

/** Several answers (the whole context, or one per opened wallet) as one: each transfer once. */
export function mergeContext(parts: readonly CaseContext[]): { nodes: Map<string, ContextNode>; edges: ContextEdge[] } {
  const nodes = new Map<string, ContextNode>()
  const edges = new Map<string, ContextEdge>()
  for (const part of parts) {
    for (const n of part.nodes) if (!nodes.has(n.id)) nodes.set(n.id, n)
    for (const e of part.edges) {
      const key = `${e.tx_hash}|${e.source}|${e.target}|${e.asset}|${e.amount}`
      if (!edges.has(key)) edges.set(key, e)
    }
  }
  return { nodes, edges: [...edges.values()] }
}

export interface ContextOptions {
  /** A wallet's "N other wallets" node the officer opened: its id → wallets drawn there. */
  shown?: ReadonlyMap<string, number>
  keep?: number
}

export interface ContextView extends FlowView {
  /** Context transfers on the picture, and those with no drawn wallet at either end. */
  contextTransfers: number
  contextHidden: number
}

/** `view` with the context laid under it. A context wallet hangs off the drawn wallet it
 *  transacted with (its anchor), in a band below the picture, half a column to the side it is
 *  on: payers to the left, payees to the right. Labelled wallets first, then by amount. */
export function withContext(view: FlowView, context: { nodes: ReadonlyMap<string, ContextNode>; edges: readonly ContextEdge[] }, opts: ContextOptions = {}): ContextView {
  const keep = opts.keep ?? CONTEXT_KEEP
  // a wallet that is drawn inside a group (an exchange's wallets, a fan, a fold) is that group here
  const drawnAs = new Map<string, FlowNode>()
  for (const n of view.nodes) for (const id of [n.id, ...n.members]) if (!drawnAs.has(id)) drawnAs.set(id, n)

  type Hang = { anchor: FlowNode; side: FanSide; other: string; amount: number; edges: ContextEdge[] }
  const between = new Map<string, FlowEdge>()
  const hangs = new Map<string, Hang>()
  let hidden = 0
  let drawn = 0
  const line = (source: string, target: string, e: ContextEdge) => {
    const id = `ctx:${source}>${target}`
    const edge = between.get(id) ?? { id, source, target, direction: 'outbound' as const, amount: 0, asset: e.asset, transfers: [], onPath: false, context: true as const, others: [] as ContextEdge[] }
    edge.amount += e.asset === edge.asset ? e.amount : 0
    edge.others!.push(e)
    between.set(id, edge)
  }
  for (const e of context.edges) {
    const a = drawnAs.get(e.source)
    const b = drawnAs.get(e.target)
    if (!a && !b) {
      hidden += 1
      continue
    }
    drawn += 1
    if (a && b) {
      if (a.id !== b.id) line(a.id, b.id, e)
      continue
    }
    const anchor = (a ?? b)!
    const side: FanSide = a ? 'out' : 'in'
    const other = a ? e.target : e.source
    const key = `${side}|${anchor.id}|${other}`
    const hang = hangs.get(key) ?? { anchor, side, other, amount: 0, edges: [] }
    hang.amount += e.amount
    hang.edges.push(e)
    hangs.set(key, hang)
  }

  // --- which context wallets are drawn: one place each, under its first anchor ---
  const groups = new Map<string, Hang[]>()
  for (const hang of hangs.values()) {
    const key = `${hang.side}:${hang.anchor.id}`
    const list = groups.get(key)
    if (list) list.push(hang)
    else groups.set(key, [hang])
  }
  const bottom = view.nodes.reduce((max, n) => Math.max(max, nodeXY(n).y), 0) + 100
  // Each half-column of the picture has a strip of the band under it, filled row by row, so a
  // wallet with much context makes the band a little deeper and not one tall column.
  const filled = new Map<number, number>()
  const place = (x: number) => {
    const i = filled.get(x) ?? 0
    filled.set(x, i + 1)
    return { x: x + ((i % BAND_ACROSS) - (BAND_ACROSS - 1) / 2) * BAND_STEP, y: bottom + Math.floor(i / BAND_ACROSS) * BAND_ROW }
  }
  const nodes: FlowNode[] = []
  const placed = new Map<string, string>() // context wallet → the node that stands for it
  const blank = { role: 'unknown' as const, row: 0, onPath: false, funder: false, named: false, received: 0, sent: 0, context: true as const }
  const order = [...groups.entries()].sort(([, a], [, b]) => nodeXY(a[0].anchor).x - nodeXY(b[0].anchor).x || a[0].anchor.id.localeCompare(b[0].anchor.id) || a[0].side.localeCompare(b[0].side))
  for (const [, list] of order) {
    const { anchor, side } = list[0]
    const x = nodeXY(anchor).x + (side === 'out' ? 1 : -1) * (COLUMN_GAP / 2)
    const fresh = list
      .filter((h) => !placed.has(h.other))
      .sort((p, q) => Number(!!context.nodes.get(q.other)?.label) - Number(!!context.nodes.get(p.other)?.label) || q.amount - p.amount || p.other.localeCompare(q.other))
    const moreId = contextMoreId(side, anchor.id)
    const limit = opts.shown?.get(moreId) ?? keep
    // one left over is drawn rather than folded into a node that says "1 other wallet"
    const cut = fresh.length - limit === 1 ? fresh.length : limit
    for (const h of fresh.slice(0, cut)) {
      const meta = context.nodes.get(h.other)
      nodes.push({ ...blank, id: h.other, kind: 'wallet', column: anchor.column, label: meta?.label ?? null, entity: meta?.label?.entity ?? null, tier: meta?.label?.tier ?? null, members: [h.other], at: place(x) })
      placed.set(h.other, h.other)
    }
    const rest = fresh.slice(cut)
    if (rest.length > 0) {
      nodes.push({ ...blank, id: moreId, kind: 'ctxmore', column: anchor.column, label: null, entity: null, tier: null, members: rest.map((h) => h.other), fan: { side, of: anchor.id }, at: place(x) })
      for (const h of rest) placed.set(h.other, moreId)
    }
  }
  for (const h of hangs.values()) {
    const stand = placed.get(h.other)!
    for (const e of h.edges) line(h.side === 'out' ? h.anchor.id : stand, h.side === 'out' ? stand : h.anchor.id, e)
  }

  return {
    ...view,
    nodes: [...view.nodes, ...nodes],
    edges: [...view.edges, ...between.values()],
    contextTransfers: drawn,
    contextHidden: hidden,
  }
}

/** The view as the trace's findings alone: without the context layer. */
export const withoutContext = (view: FlowView): FlowView => ({ ...view, nodes: view.nodes.filter((n) => !n.context), edges: view.edges.filter((e) => !e.context) })
