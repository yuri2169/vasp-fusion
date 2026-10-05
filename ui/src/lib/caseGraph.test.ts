import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { MOCK_CASES, REAL_CASES, readCase, readMock } from '../test/files'
import { buildFlow, clusterable, edgeWidth, focusOf, ledgerOf, mainPath, nodeXY, pathTo, traced } from './caseGraph'

const mock = (id: string) => readMock<CaseDetail>(`cases/${id}.json`)
const real = (id: string) => readCase<CaseDetail>(id)
const everyCase = (): [string, CaseDetail][] => [
  ...MOCK_CASES.map((id): [string, CaseDetail] => [id, mock(id)]),
  ...REAL_CASES.map((id): [string, CaseDetail] => [id, real(id)]),
]

const okx = mock('demo-tron-okx')
const hero = real('tron-coindcx')
const node = (view: ReturnType<typeof buildFlow>, start: string) => view.nodes.find((n) => n.id.startsWith(start))!

describe('mainPath', () => {
  it('is the path the Hop Rail shows, from the suspect wallet', () => {
    expect(mainPath(okx).map((a) => a.slice(0, 6))).toEqual(['TVZpWt', 'TTYBTv', 'TPJMWH', 'THS5KL'])
    expect(mainPath(hero).map((a) => a.slice(0, 6))).toEqual(['TYJD2h', 'TCw8j3'])
  })

  it('is the wallet alone when nothing was reached', () => {
    expect(mainPath({ ...okx, hop_rail: [], candidates: [] })).toEqual([okx.address])
  })
})

describe('buildFlow', () => {
  it('puts the suspect wallet at column 0, row 0', () => {
    for (const [, c] of everyCase()) {
      const suspect = buildFlow(c).nodes.find((n) => n.id === c.address)!
      expect([suspect.column, suspect.row, suspect.role]).toEqual([0, 0, 'suspect'])
    }
  })

  it('keeps the main path on one line, in hop order', () => {
    const view = buildFlow(okx)
    const path = mainPath(okx).map((a) => view.nodes.find((n) => n.id === a)!)
    expect(path.map((n) => n.row)).toEqual([0, 0, 0, 0])
    expect(path.map((n) => n.column)).toEqual([0, 1, 2, 3])
    expect(path.every((n) => n.onPath)).toBe(true)
    expect(view.nodes.filter((n) => n.onPath)).toHaveLength(4)
    expect(view.edges.filter((e) => e.onPath).map((e) => e.id)).toEqual(
      [0, 1, 2].map((i) => `${mainPath(okx)[i]}>${mainPath(okx)[i + 1]}`),
    )
  })

  it('hangs side branches under the main line', () => {
    const view = buildFlow(okx)
    for (const n of view.nodes.filter((x) => !x.onPath)) expect(n.row).toBeGreaterThan(0)
  })

  it('puts a wallet that only paid the suspect wallet to its left, as a funder', () => {
    const view = buildFlow(hero)
    const funders = view.nodes.filter((n) => n.funder)
    expect(funders.map((n) => n.id.slice(0, 6)).sort()).toEqual(['TJ5usJ', 'TT9b4u', 'TYASr5'])
    expect(funders.every((n) => n.column === -1)).toBe(true)
    // the largest funder is nearest the suspect wallet's line
    // ... either side of it, and the line itself is left to the money coming in
    expect(funders.sort((a, b) => Math.abs(a.row) - Math.abs(b.row) || b.row - a.row).map((n) => n.id.slice(0, 6))).toEqual(['TT9b4u', 'TJ5usJ', 'TYASr5'])
    expect(funders.map((n) => n.row)).toEqual([1, -1, 2])
    expect(view.nodes.filter((n) => !n.funder && n.id !== hero.address).every((n) => n.column > 0)).toBe(true)
  })

  it('draws several transfers between two wallets as one edge', () => {
    const view = buildFlow(hero)
    const edge = view.edges.find((e) => e.source.startsWith('TT9b4u'))!
    expect(edge.transfers).toHaveLength(3)
    expect(edge.amount).toBeCloseTo(941 + 590 + 801)
    expect(edge.direction).toBe('inbound')
    expect(edge.transfers.map((t) => t.block_time)).toEqual([...edge.transfers.map((t) => t.block_time)].sort())
    expect(view.edges).toHaveLength(6)
    expect(view.maxAmount).toBeCloseTo(2332)
    expect(view.asset).toBe('USDT')
  })

  it('never puts two wallets in the same place', () => {
    for (const [id, c] of everyCase())
      for (const collapse of [false, true]) {
        const view = buildFlow(c, { collapse })
        const places = view.nodes.map((n) => `${n.column}:${n.row}`)
        expect(new Set(places).size, `${id} collapse=${collapse}`).toBe(places.length)
      }
  })

  it('fills each column from the top, leaving the first line to the main path', () => {
    for (const [id, c] of everyCase()) {
      const view = buildFlow(c)
      const columns = new Map<number, number[]>()
      for (const n of view.nodes) columns.set(n.column, [...(columns.get(n.column) ?? []), n.row])
      for (const [column, rows] of columns) {
        const sorted = [...rows].sort((a, b) => a - b)
        if (column === -1 && rows.length > 1) {
          // payers stand either side of the suspect wallet's line, nearest first
          expect(sorted, `${id} payers`).toEqual(rows.map((_, i) => (i % 2 === 0 ? 1 : -1) * (Math.floor(i / 2) + 1)).sort((a, b) => a - b))
          continue
        }
        const first = column > 0 && !view.nodes.some((n) => n.column === column && n.onPath) ? 1 : 0
        expect(sorted, `${id} column ${column}`).toEqual(sorted.map((_, i) => first + i))
      }
    }
  })

  it('gives every edge two ends that are in the view', () => {
    for (const [id, c] of everyCase())
      for (const collapse of [false, true]) {
        const view = buildFlow(c, { collapse })
        const ids = new Set(view.nodes.map((n) => n.id))
        for (const e of view.edges) expect(ids.has(e.source) && ids.has(e.target), `${id} ${e.id}`).toBe(true)
      }
  })

  it('marks the wallets of the exchange the case names, and no others', () => {
    const view = buildFlow(okx)
    expect(view.nodes.filter((n) => n.named).map((n) => n.id.slice(0, 6)).sort()).toEqual(['T9zbp5', 'THS5KL'])
    expect(buildFlow(mock('demo-eth-abstain')).nodes.some((n) => n.named)).toBe(false)
    // sanctioned with a nearest exchange under the bar: it is not named
    expect(buildFlow(mock('demo-tron-sanctioned')).nodes.some((n) => n.named)).toBe(false)
  })

  it('carries the label, owner and tier of a labelled wallet', () => {
    const deposit = node(buildFlow(hero), 'TCw8j3')
    expect([deposit.entity, deposit.tier, deposit.role, deposit.kind]).toEqual(['CoinDCX', 'derived', 'exchange_deposit', 'wallet'])
    expect(deposit.members).toEqual([deposit.id])
    expect(deposit.received).toBeCloseTo(1530)
    expect(node(buildFlow(hero), 'TDYCQE').sent).toBeCloseTo(1122.22)
  })

  it('groups the wallets of one exchange into one node when asked', () => {
    const open = buildFlow(okx)
    const view = buildFlow(okx, { collapse: true })
    const group = view.nodes.find((n) => n.id === 'cluster:OKX')!
    expect(group.kind).toBe('cluster')
    expect(group.members.map((a) => a.slice(0, 6))).toEqual(['THS5KL', 'T9zbp5'])
    expect([group.entity, group.role, group.column, group.row, group.onPath, group.named]).toEqual(['OKX', 'exchange_deposit', 3, 0, true, true])
    expect(view.nodes).toHaveLength(open.nodes.length - 1)
    // the sweep inside OKX is no longer an edge; the payment into it is re-pointed
    expect(view.edges.some((e) => e.source === 'cluster:OKX')).toBe(false)
    expect(view.edges.find((e) => e.target === 'cluster:OKX')!.source.slice(0, 6)).toBe('TPJMWH')
    // one HTX wallet: it stays a wallet
    expect(view.nodes.some((n) => n.id === 'cluster:HTX')).toBe(false)
  })
})

describe('clusterable', () => {
  it('is true only when some exchange has two or more wallets in the graph', () => {
    expect(clusterable(okx)).toBe(true)
    expect(clusterable(hero)).toBe(false)
  })
})

describe('pathTo', () => {
  it('is the chain of wallets and transfers from the suspect wallet', () => {
    const view = buildFlow(okx)
    const htx = node(view, 'TAuUCi')
    const { nodes, edges } = pathTo(view, htx.id)
    expect([...nodes].map((a) => a.slice(0, 6))).toEqual(['TVZpWt', 'TTYBTv', 'TFyHFD', 'TSgt1s', 'TAuUCi'])
    expect(edges.size).toBe(4)
  })

  it('for a funder is the payment into the suspect wallet', () => {
    const view = buildFlow(hero)
    const { nodes, edges } = pathTo(view, node(view, 'TT9b4u').id)
    expect([...nodes].map((a) => a.slice(0, 6))).toEqual(['TT9b4u', 'TYJD2h'])
    expect(edges.size).toBe(1)
  })

  it('for the suspect wallet is itself; for an unknown id, nothing', () => {
    const view = buildFlow(hero)
    expect([...pathTo(view, hero.address).nodes]).toEqual([hero.address])
    expect(pathTo(view, 'nope').nodes.size).toBe(0)
  })

  it('reaches every wallet of every case', () => {
    for (const [id, c] of everyCase()) {
      const view = buildFlow(c)
      for (const n of view.nodes) expect(pathTo(view, n.id).nodes.has(n.id), `${id} ${n.id}`).toBe(true)
    }
  })
})

describe('focusOf', () => {
  it('is the path to the wallet being looked at: everything else steps back', () => {
    const view = buildFlow(okx)
    const focus = focusOf(view, node(view, 'TAuUCi').id)!
    expect(focus.nodes.size).toBe(5)
    expect(focus.edges.size).toBe(4)
  })

  it('is nothing for the suspect wallet (every transfer is its own), for no selection, and for an unknown wallet', () => {
    const view = buildFlow(okx)
    expect(focusOf(view, okx.address)).toBeNull()
    expect(focusOf(view, null)).toBeNull()
    expect(focusOf(view, 'nope')).toBeNull()
  })
})

describe('nodeXY and edgeWidth', () => {
  it('lays columns left to right and rows downwards', () => {
    expect(nodeXY({ column: 0, row: 0 })).toEqual({ x: 0, y: 0 })
    expect(nodeXY({ column: 2, row: 1 }).x).toBeGreaterThan(nodeXY({ column: 1, row: 1 }).x)
    expect(nodeXY({ column: -1, row: 0 }).x).toBeLessThan(0)
    expect(nodeXY({ column: 1, row: 2 }).y).toBeGreaterThan(nodeXY({ column: 1, row: 1 }).y)
  })

  it('is 1.5 for nothing, 8 for the largest, and grows with the amount', () => {
    expect(edgeWidth(0, 100)).toBe(1.5)
    expect(edgeWidth(100, 100)).toBe(8)
    expect(edgeWidth(25, 100)).toBeGreaterThan(edgeWidth(4, 100))
    expect(edgeWidth(25, 100)).toBeLessThan(edgeWidth(100, 100))
    expect(edgeWidth(5, 0)).toBe(1.5)
  })
})

describe('traced and ledgerOf', () => {
  it('is the part of a transfer that is the suspect wallet’s money', () => {
    expect(traced({ amount: 11000, traced_amount: 5800 })).toBe(5800)
    expect(traced({ amount: 11000, traced_amount: null })).toBe(11000)
    expect(traced({ amount: 11000 })).toBe(11000)
  })

  it('lists what came into and went out of one wallet, in time order', () => {
    const ledger = ledgerOf(hero, hero.address)
    expect(ledger.incoming).toHaveLength(5)
    expect(ledger.outgoing).toHaveLength(2)
    expect(ledger.received).toBeCloseTo(2695)
    expect(ledger.sent).toBeCloseTo(2652.22)
    expect(ledger.incoming.map((e) => e.block_time)).toEqual([...ledger.incoming.map((e) => e.block_time)].sort())
  })
})
