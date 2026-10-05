import { describe, expect, it } from 'vitest'
import type { CaseContext, CaseDetail } from '../api/models'
import { buildFlow, nodeXY } from '../lib/caseGraph'
import { mergeContext, withContext } from '../lib/context'
import { REAL_CASES, readCase, readContext } from '../test/files'
import { homeView, moveCamera, to3D } from './flowSpace'
import { toElements } from './flowStyle'

const hero = readCase<CaseDetail>('tron-coindcx')
const context = readContext<CaseContext>('tron-coindcx')
const space = (c: CaseDetail, withCtx = false) => {
  const trail = buildFlow(c)
  const view = withCtx ? withContext(trail, mergeContext([context])) : trail
  const elements = toElements(view)
  return { view, elements, ...to3D(view, elements) }
}
const dist = (a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }) => Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z)

describe('the 3D view is the 2D view, turned', () => {
  it('has the same wallets and the same transfers as the 2D canvas, for every recorded case', () => {
    for (const id of REAL_CASES) {
      const { elements, nodes, links } = space(readCase<CaseDetail>(id))
      expect(nodes.map((n) => n.id).sort(), id).toEqual(elements.filter((e) => e.group === 'nodes' && !e.data.owner).map((e) => e.data.id!).sort())
      expect(links.map((l) => l.id).sort(), id).toEqual(elements.filter((e) => e.group === 'edges').map((e) => e.data.id!).sort())
    }
  })

  it('and the same again with context on: the greyed layer comes along, still marked', () => {
    const { elements, nodes, links } = space(hero, true)
    expect(nodes).toHaveLength(elements.filter((e) => e.group === 'nodes' && !e.data.owner).length)
    expect(nodes.filter((n) => n.data.context).length).toBeGreaterThan(0)
    expect(links.filter((l) => l.data.context).length).toBeGreaterThan(0)
  })

  it('carries each tile as the 2D stylesheet reads it: role, tier, size, the named exchange, the name over it', () => {
    const { elements, nodes } = space(hero)
    for (const n of nodes) expect(n.data).toBe(elements.find((e) => e.data.id === n.id)!.data)
    const named = nodes.find((n) => n.data.named === 1)!
    expect(named.caption).toBe('CoinDCX')
    expect(nodes.find((n) => n.data.role === 'suspect')!.caption).toBe('Suspect')
  })

  it('keeps hop depth on one axis, as in 2D, with the Hop Rail path along it', () => {
    const { view, nodes } = space(hero)
    for (const n of nodes) expect(n.x).toBe(nodeXY(view.nodes.find((v) => v.id === n.id)!).x)
    for (const v of view.nodes.filter((x) => x.onPath)) {
      const n = nodes.find((x) => x.id === v.id)!
      expect([n.y, n.z]).toEqual([0, 0])
    }
  })

  it('puts no two wallets in one place, and is the same every time', () => {
    for (const withCtx of [false, true]) {
      const { nodes } = space(hero, withCtx)
      for (const [i, a] of nodes.entries()) for (const b of nodes.slice(i + 1)) expect(dist(a, b), `${a.id} ${b.id}`).toBeGreaterThan(10)
      expect(space(hero, withCtx).nodes).toEqual(nodes)
    }
  })
})

describe('the camera', () => {
  const { nodes } = space(hero)
  const home = homeView(nodes)

  it('opens looking at the middle of the picture, from far enough to see all of it', () => {
    const xs = nodes.map((n) => n.x)
    expect(home.lookAt.x).toBeCloseTo((Math.min(...xs) + Math.max(...xs)) / 2)
    expect(dist(home.position, home.lookAt)).toBeGreaterThan(Math.max(...xs) - Math.min(...xs))
  })

  it('turns about the point it looks at, without changing its distance', () => {
    const turned = moveCamera(home.position, home.lookAt, { turn: 0.5, tilt: -0.2 })
    expect(turned.lookAt).toEqual(home.lookAt)
    expect(dist(turned.position, turned.lookAt)).toBeCloseTo(dist(home.position, home.lookAt))
    expect(turned.position).not.toEqual(home.position)
  })

  it('zooms by moving nearer, and moves sideways with the point it looks at', () => {
    const near = moveCamera(home.position, home.lookAt, { zoom: 0.5 })
    expect(dist(near.position, near.lookAt)).toBeCloseTo(dist(home.position, home.lookAt) / 2)
    const moved = moveCamera(home.position, home.lookAt, { panX: 40, panY: 10 })
    expect(dist(moved.lookAt, home.lookAt)).toBeCloseTo(Math.hypot(40, 10))
    expect(dist(moved.position, moved.lookAt)).toBeCloseTo(dist(home.position, home.lookAt))
  })

  it('never tips over the top, however long the key is held', () => {
    let at = home
    for (let i = 0; i < 100; i++) at = moveCamera(at.position, at.lookAt, { tilt: -0.1 })
    expect(at.position.y).toBeGreaterThan(at.lookAt.y)
    expect(Number.isFinite(at.position.x + at.position.y + at.position.z)).toBe(true)
  })
})
