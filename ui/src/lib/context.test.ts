import { describe, expect, it } from 'vitest'
import type { CaseContext, CaseDetail } from '../api/models'
import { toElements } from '../case/flowStyle'
import { readCase, readContext } from '../test/files'
import { buildFlow, focusOf, nodeXY, pathTo } from './caseGraph'
import { CONTEXT_KEEP, CONTEXT_MORE, contextMoreId, mergeContext, withContext, withoutContext } from './context'
import { replaySteps, shownAt } from './replay'

/** A recorded case and the context the API gave for it (src/test/fixtures/cases/README.md). */
const hero = readCase<CaseDetail>('tron-coindcx')
const ctx = readContext<CaseContext>('tron-coindcx')
const trail = buildFlow(hero)
const merged = mergeContext([ctx])
const view = withContext(trail, merged)

describe('the context of a recorded case', () => {
  it('is everything the trace saw and did not follow', () => {
    const s = hero.trace_summary!
    expect(ctx.transfers).toBe(s.transfers_seen - s.transfers_followed)
    expect(ctx.edges).toHaveLength(ctx.transfers)
  })

  it('counts each transfer once, however many answers carry it', () => {
    expect(mergeContext([ctx, ctx]).edges).toHaveLength(ctx.edges.length)
  })
})

describe('withContext', () => {
  it('adds a marked layer and leaves the trail exactly as it was', () => {
    const before = JSON.stringify(trail)
    const added = withContext(trail, merged)
    expect(JSON.stringify(trail)).toBe(before)
    expect(added.nodes.slice(0, trail.nodes.length)).toEqual(trail.nodes)
    expect(added.edges.slice(0, trail.edges.length)).toEqual(trail.edges)
    expect(added.nodes.slice(trail.nodes.length).every((n) => n.context)).toBe(true)
    expect(added.edges.slice(trail.edges.length).every((e) => e.context)).toBe(true)
    expect(withoutContext(added)).toEqual({ ...added, nodes: trail.nodes, edges: trail.edges })
  })

  it('draws every context transfer that has a drawn wallet at one end, each once', () => {
    const others = view.edges.flatMap((e) => e.others ?? [])
    expect(others).toHaveLength(view.contextTransfers)
    expect(new Set(others.map((e) => e.id)).size).toBe(others.length)
    expect(view.contextTransfers + view.contextHidden).toBe(ctx.edges.length)
  })

  it('keeps it bounded: a few wallets each way for a wallet, the rest one node that says how many', () => {
    const more = view.nodes.filter((n) => n.kind === 'ctxmore')
    expect(more.length).toBeGreaterThan(0)
    for (const n of more) expect(n.members.length).toBeGreaterThan(1)
    const drawn = view.nodes.filter((n) => n.context && n.kind === 'wallet')
    const sides = new Set(view.edges.filter((e) => e.context).map((e) => (trail.nodes.some((n) => n.id === e.source) ? `out:${e.source}` : `in:${e.target}`)))
    expect(drawn.length).toBeLessThanOrEqual(sides.size * (CONTEXT_KEEP + 1))
    // nobody is lost: drawn, or counted in a group
    const all = new Set([...drawn.map((n) => n.id), ...more.flatMap((n) => n.members)])
    const offTrail = [...merged.nodes.values()].filter((n) => !n.on_graph && view.edges.some((e) => (e.others ?? []).some((o) => o.source === n.id || o.target === n.id)))
    expect(all.size).toBe(offTrail.length)
  })

  it('draws more of one wallet’s context when its group is opened', () => {
    const group = view.nodes.find((n) => n.kind === 'ctxmore')!
    const opened = withContext(trail, merged, { shown: new Map([[group.id, CONTEXT_KEEP + CONTEXT_MORE]]) })
    const before = view.nodes.filter((n) => n.context && n.kind === 'wallet').length
    const after = opened.nodes.filter((n) => n.context && n.kind === 'wallet').length
    expect(after - before).toBe(Math.min(CONTEXT_MORE, group.members.length))
    expect(group.id).toBe(contextMoreId(group.fan!.side, group.fan!.of))
  })

  it('puts context under the picture, never on a wallet of the trail or on each other', () => {
    const lowest = Math.max(...trail.nodes.map((n) => nodeXY(n).y))
    const places = view.nodes.filter((n) => n.context).map((n) => nodeXY(n))
    expect(places.every((p) => p.y > lowest)).toBe(true)
    expect(new Set(places.map((p) => `${p.x}:${p.y}`)).size).toBe(places.length)
  })
})

describe('context never changes the answer', () => {
  it('the replay plays the trail only', () => {
    expect(replaySteps(view)).toEqual(replaySteps(trail))
    const steps = replaySteps(view)
    const mid = shownAt(view, steps, 1)
    expect([...mid.nodes].every((id) => trail.nodes.some((n) => n.id === id))).toBe(true)
  })

  it('the path to a wallet is the trail’s', () => {
    for (const n of trail.nodes) {
      expect(pathTo(view, n.id)).toEqual(pathTo(trail, n.id))
      expect(focusOf(view, n.id)).toEqual(focusOf(trail, n.id))
    }
  })

  it('the trail is drawn the same with context on: same tiles, sizes, widths and amounts', () => {
    const plain = toElements(buildFlow(hero))
    const both = toElements(withContext(buildFlow(hero), merged))
    const trailOnly = both.filter((el) => !el.data.context)
    expect(trailOnly).toEqual(plain)
    const extra = both.filter((el) => el.data.context)
    expect(extra.length).toBeGreaterThan(0)
    // quiet: no amount on a context line, no name under a context wallet until asked
    expect(extra.every((el) => el.data.label === '')).toBe(true)
  })
})
