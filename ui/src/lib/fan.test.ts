import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { fanCase } from '../../scripts/big-graph.mjs'
import { REAL_CASES, readCase } from '../test/files'
import { buildFlow, FAN_COLUMN, FAN_KEEP, fanId, nodeXY, pathTo, type FlowView } from './caseGraph'

const ten = fanCase(10)
const fifty = fanCase(50)
const inId = (c: CaseDetail) => fanId('in', c.address)

describe('a fan of payers', () => {
  it('draws the four largest and one node for the rest, with their number and their sum', () => {
    const view = buildFlow(ten)
    const payers = view.nodes.filter((n) => n.column === -1)
    expect(payers.filter((n) => n.kind === 'wallet').map((n) => n.id).sort()).toEqual(['p0001', 'p0002', 'p0003', 'p0004'])
    const group = view.nodes.find((n) => n.id === inId(ten))!
    expect(group.kind).toBe('fan')
    expect(group.fan).toEqual({ side: 'in', of: ten.address })
    expect(group.members).toHaveLength(10 - FAN_KEEP)
    const rest = ten.graph.edges.filter((e) => group.members.includes(e.source))
    expect(group.sent).toBeCloseTo(rest.reduce((s, e) => s + e.amount, 0))
    const line = view.edges.find((e) => e.source === group.id)!
    expect([line.target, line.direction, line.fan, line.transfers.length]).toEqual([ten.address, 'inbound', 'in', 6])
    expect(line.amount).toBeCloseTo(group.sent)
  })

  it('loses nothing: what came in is the same grouped, opened or ungrouped', () => {
    const into = (view: FlowView) => view.edges.filter((e) => e.direction === 'inbound').reduce((s, e) => s + e.amount, 0)
    const wallets = (view: FlowView) => view.nodes.reduce((n, x) => n + x.members.length, 0)
    const all = buildFlow(fifty, { fans: false })
    for (const view of [buildFlow(fifty), buildFlow(fifty, { openFans: new Set([inId(fifty)]) })]) {
      expect(into(view)).toBeCloseTo(into(all))
      expect(wallets(view)).toBe(wallets(all))
    }
  })

  it('never hides a labelled payer in the group', () => {
    // the label's wording is the test's own: only "it has a label" matters here
    const label = { entity: 'A labelled payer', category: 'exchange', kind: 'hot', tier: 'curated', confidence: 0.9 }
    const c = { ...ten, graph: { ...ten.graph, nodes: ten.graph.nodes.map((n) => (n.id === 'p0010' ? { ...n, label } : n)) } } as unknown as CaseDetail
    const view = buildFlow(c)
    expect(view.nodes.find((n) => n.id === 'p0010')?.kind).toBe('wallet')
    expect(view.nodes.find((n) => n.id === inId(c))!.members).not.toContain('p0010')
  })

  it('opens in place: every payer drawn, none on the line the money comes in along', () => {
    const view = buildFlow(fifty, { openFans: new Set([inId(fifty)]) })
    const payers = view.nodes.filter((n) => n.funder)
    expect(payers).toHaveLength(50)
    expect(payers.every((n) => n.kind === 'wallet')).toBe(true)
    const places = view.nodes.map((n) => nodeXY(n)).map((p) => `${p.x}:${p.y}`)
    expect(new Set(places).size).toBe(places.length)
    expect(payers.every((n) => nodeXY(n).y !== 0 && nodeXY(n).x < 0)).toBe(true)
    // a grid, not one column 50 wallets tall
    expect(new Set(payers.map((n) => nodeXY(n).x)).size).toBe(50 / FAN_COLUMN)
    expect(view.edges.filter((e) => e.direction === 'inbound').every((e) => e.fan === 'in')).toBe(true)
  })

  it('leaves the line free whenever two or more wallets paid in, the largest nearest', () => {
    const view = buildFlow(ten)
    const rows = view.nodes.filter((n) => n.column === -1 && n.kind === 'wallet').sort((a, b) => b.sent - a.sent)
    expect(rows.map((n) => n.row)).toEqual([1, -1, 2, -2])
    expect(view.nodes.filter((n) => n.column === -1).every((n) => n.row !== 0)).toBe(true)
  })

  it('finds a grouped wallet when asked without fans', () => {
    expect(pathTo(buildFlow(ten, { fans: false }), 'p0009').nodes).toEqual(new Set(['p0009', ten.address]))
  })
})

describe('a fan of payees', () => {
  const out = fanCase(0, 12)
  it('is grouped the same way, past the four largest', () => {
    const view = buildFlow(out)
    const group = view.nodes.find((n) => n.kind === 'fan')!
    expect(group.fan).toEqual({ side: 'out', of: out.address })
    // one payee is the Hop Rail's path and is not part of the fan
    expect(group.members).toHaveLength(12 - 1 - FAN_KEEP)
    expect(view.edges.find((e) => e.target === group.id)?.fan).toBe('out')
    expect(view.nodes.filter((n) => n.onPath)).toHaveLength(2)
  })
})

describe('recorded cases', () => {
  it('keep every wallet: drawn, or counted in a fan', () => {
    for (const id of REAL_CASES) {
      const c = readCase<CaseDetail>(id)
      const view = buildFlow(c)
      const grouped = view.nodes.filter((n) => n.kind === 'fan').flatMap((n) => n.members).length
      expect(view.nodes.filter((n) => n.kind === 'wallet').length + grouped, id).toBe(c.graph.nodes.length)
    }
  })
})
