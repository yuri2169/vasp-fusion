import { bigCase } from '../../scripts/big-graph.mjs'
import { toElements } from '../case/flowStyle'
import { BIG_GRAPH, buildFlow, foldFlow, pathTo } from './caseGraph'

const c = bigCase(2000)
const ms = (fn: () => unknown) => {
  const t = performance.now()
  fn()
  return performance.now() - t
}

describe('a graph of 2,000 wallets (a synthetic shape, scripts/big-graph.mjs)', () => {
  it('is the size the brief names', () => {
    expect(c.graph.nodes).toHaveLength(2000)
    expect(c.graph.edges.length).toBeGreaterThan(2500)
    expect(c.graph.nodes.length).toBeGreaterThan(BIG_GRAPH)
  })

  it('is laid out in well under a frame budget of the page (100 ms)', () => {
    buildFlow(c) // warm
    const layout = Math.min(...[0, 1, 2].map(() => ms(() => buildFlow(c))))
    expect(layout).toBeLessThan(100)
  })

  const full = buildFlow(c)
  const folded = foldFlow(full, { perColumn: 12, maxHop: 2 })

  it('draws a bounded part: the largest of each hop, the rest folded into one node a hop', () => {
    expect(folded.nodes.length).toBeLessThan(80)
    expect(toElements(folded).length).toBeLessThan(400)
    const more = folded.nodes.filter((n) => n.kind === 'more')
    expect(more.length).toBeGreaterThan(0)
    for (const m of more) expect(m.id).toBe(`more:${m.column}`)
    // No hop past the limit is drawn, and the page is told how many wallets wait there.
    expect(Math.max(...folded.nodes.map((n) => Math.abs(n.column)))).toBe(2)
    expect(folded.beyond).toEqual({ hop: 3, wallets: full.nodes.filter((n) => Math.abs(n.column) > 2).length })
  })

  it('loses no wallet and no money: every wallet up to the hop limit is drawn or counted in a fold', () => {
    const within = full.nodes.filter((n) => Math.abs(n.column) <= 2)
    const drawn = folded.nodes.flatMap((n) => n.members)
    expect(new Set(drawn).size).toBe(drawn.length)
    expect(drawn.length).toBe(within.length)
    const sum = (edges: { amount: number }[]) => Math.round(edges.reduce((a, e) => a + e.amount, 0) * 100)
    const ids = new Set(within.map((n) => n.id))
    expect(sum(folded.edges)).toBe(sum(full.edges.filter((e) => ids.has(e.source) && ids.has(e.target))))
    expect(folded.folded).toEqual(folded.nodes.filter((n) => n.kind === 'more').map((n) => ({ column: n.column, wallets: n.members.length })))
  })

  it('keeps the path, and any wallet asked for, out of the folds', () => {
    const deep = full.nodes.filter((n) => n.column === 2).at(-1)!
    const asked = foldFlow(full, { perColumn: 12, maxHop: 2, keep: pathTo(full, deep.id).nodes })
    expect(asked.nodes.find((n) => n.id === deep.id)?.kind).toBe('wallet')
    for (const n of full.nodes.filter((x) => x.onPath)) expect(folded.nodes.some((x) => x.id === n.id)).toBe(true)
    expect(folded.nodes.filter((n) => n.onPath).every((n) => n.row === 0)).toBe(true)
  })

  it('opens a hop further when asked: more wallets of one hop, or the next hop', () => {
    const wider = foldFlow(full, { perColumn: 12, maxHop: 2, shown: new Map([[2, 62]]) })
    expect(wider.nodes.filter((n) => n.column === 2 && n.kind === 'wallet').length).toBe(62)
    const deeper = foldFlow(full, { perColumn: 12, maxHop: 3 })
    expect(deeper.beyond?.hop).toBe(4)
    const all = foldFlow(full, { perColumn: 12, maxHop: null })
    expect(all.beyond).toBeNull()
  })

  it('folding is fast too (25 ms) and leaves a small graph as it is', () => {
    const fold = Math.min(...[0, 1, 2].map(() => ms(() => foldFlow(full, { perColumn: 12, maxHop: 2 }))))
    expect(fold).toBeLessThan(25)
    const small = buildFlow(bigCase(30, 2))
    const same = foldFlow(small, { perColumn: 40, maxHop: null })
    expect(same.nodes.map((n) => n.id).sort()).toEqual(small.nodes.map((n) => n.id).sort())
    expect(same.folded).toEqual([])
  })
})
