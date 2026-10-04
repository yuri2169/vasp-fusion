import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { readCase } from '../test/files'
import { buildFlow } from './caseGraph'
import { replaySteps, shownAt } from './replay'

const view = buildFlow(readCase<CaseDetail>('tron-coindcx'), { collapse: false })
const steps = replaySteps(view)

describe('replaySteps', () => {
  it('has one step per drawn edge, in block-time order', () => {
    expect(steps.map((s) => s.edge).sort()).toEqual(view.edges.map((e) => e.id).sort())
    const times = steps.map((s) => s.time).filter(Boolean) as string[]
    expect(times).toEqual([...times].sort())
    expect(times.length).toBeGreaterThan(0)
  })

  it('carries the real amount of each edge, untouched', () => {
    for (const s of steps) expect(s.amount).toBe(view.edges.find((e) => e.id === s.edge)!.amount)
  })

  it('is the same every time', () => {
    expect(replaySteps(view)).toEqual(steps)
  })
})

describe('shownAt', () => {
  it('starts with only the wallet the case is about', () => {
    const { nodes, edges } = shownAt(view, steps, 0)
    expect(edges.size).toBe(0)
    expect([...nodes]).toEqual(view.nodes.filter((n) => n.column === 0).map((n) => n.id))
  })

  it('adds one transfer and its two wallets per step, and ends with everything that has a transfer', () => {
    const one = shownAt(view, steps, 1)
    expect([...one.edges]).toEqual([steps[0].edge])
    expect(one.nodes.has(steps[0].source) && one.nodes.has(steps[0].target)).toBe(true)
    const all = shownAt(view, steps, steps.length)
    expect(all.edges.size).toBe(view.edges.length)
    const touched = new Set(view.edges.flatMap((e) => [e.source, e.target]))
    for (const id of touched) expect(all.nodes.has(id), id).toBe(true)
  })
})
