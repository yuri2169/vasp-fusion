/** The 2D picture's own elements, placed in space for the 3D view.
 *
 *  The 3D view is the 2D view turned: the same wallets and transfers (context on or off,
 *  grouped or not), the same tile for each role, the same colours. So it is built from the
 *  elements Cytoscape was given, not from the case again. Hop depth is the x axis, as in 2D.
 *  The Hop Rail's path runs along that axis; the other wallets of a hop stand around it on a
 *  disc, the larger nearer the axis. Every position is worked out here, the same every time:
 *  nothing settles, nothing drifts. */
import type { ElementDefinition } from 'cytoscape'
import type { FlowView } from '../lib/caseGraph'
import { nodeXY } from '../lib/caseGraph'

export interface Node3D {
  id: string
  x: number
  y: number
  z: number
  /** The element's data as the 2D stylesheet reads it (role, tier, named, side, kind, context…). */
  data: Record<string, unknown>
  /** What is written under the tile, and over it. */
  label: string
  caption: string | null
  threat: boolean
}

export interface Link3D {
  id: string
  source: string
  target: string
  data: Record<string, unknown>
}

const GOLDEN = Math.PI * (3 - Math.sqrt(5))
/** How far apart the wallets of one hop stand on their disc. */
const SPREAD = 98
const CONTEXT_SPREAD = 30

export function to3D(view: FlowView, elements: readonly ElementDefinition[]): { nodes: Node3D[]; links: Link3D[] } {
  const captions = new Map<string, ElementDefinition>()
  for (const el of elements) if (el.group === 'nodes' && el.data.owner) captions.set(el.data.owner as string, el)
  const dataOf = new Map<string, ElementDefinition>()
  for (const el of elements) if (el.group === 'nodes' && !el.data.owner) dataOf.set(el.data.id!, el)

  // the wallets of each plane across the axis, in the order the 2D layout ranked them
  const planes = new Map<number, typeof view.nodes>()
  for (const n of view.nodes) {
    const x = nodeXY(n).x
    const list = planes.get(x)
    if (list) list.push(n)
    else planes.set(x, [n])
  }
  const nodes: Node3D[] = []
  for (const [x, list] of [...planes.entries()].sort(([a], [b]) => a - b)) {
    const off = list.filter((n) => !(n.onPath || n.column === 0) || n.context).sort((a, b) => Math.abs(nodeXY(a).y) - Math.abs(nodeXY(b).y) || nodeXY(a).y - nodeXY(b).y || a.id.localeCompare(b.id))
    const rank = new Map(off.map((n, i) => [n.id, i + 1]))
    for (const n of list) {
      const el = dataOf.get(n.id)
      if (!el) continue
      const k = rank.get(n.id) ?? 0
      const r = k === 0 ? 0 : (n.context ? CONTEXT_SPREAD : SPREAD) * Math.sqrt(k + 0.6)
      const caption = captions.get(n.id)
      nodes.push({
        id: n.id,
        x,
        // the disc opens downwards first, as the side branches hang under the path in 2D
        y: (k === 0 ? 0 : -r * Math.cos(k * GOLDEN)) - (n.context ? 3 * SPREAD : 0),
        z: r * Math.sin(k * GOLDEN),
        data: el.data as Record<string, unknown>,
        // a context wallet is named when pointed at; only a group of them says how many
        label: n.context ? (n.kind === 'ctxmore' ? ((el.data.name as string) ?? '') : '') : ((el.data.label as string) ?? ''),
        caption: (caption?.data.label as string) ?? null,
        threat: String(caption?.classes ?? '').includes('threat'),
      })
    }
  }
  const ids = new Set(nodes.map((n) => n.id))
  const links: Link3D[] = []
  for (const el of elements) {
    if (el.group !== 'edges' || !ids.has(el.data.source) || !ids.has(el.data.target)) continue
    links.push({ id: el.data.id!, source: el.data.source, target: el.data.target, data: el.data as Record<string, unknown> })
  }
  return { nodes, links }
}

/** Where the camera stands to see all of it: off to the front, a little above, looking at the middle. */
export function homeView(nodes: readonly Node3D[]): { position: { x: number; y: number; z: number }; lookAt: { x: number; y: number; z: number } } {
  if (nodes.length === 0) return { position: { x: 0, y: 0, z: 400 }, lookAt: { x: 0, y: 0, z: 0 } }
  const min = { x: Infinity, y: Infinity, z: Infinity }
  const max = { x: -Infinity, y: -Infinity, z: -Infinity }
  for (const n of nodes)
    for (const axis of ['x', 'y', 'z'] as const) {
      min[axis] = Math.min(min[axis], n[axis])
      max[axis] = Math.max(max[axis], n[axis])
    }
  const lookAt = { x: (min.x + max.x) / 2, y: (min.y + max.y) / 2, z: (min.z + max.z) / 2 }
  // Far enough for the wider side to fit, text and all. The camera sees 40 degrees top to
  // bottom: 0.73 of its distance in height, and about 0.94 in width in the panel's frame.
  const distance = Math.max((max.x - min.x + 220) / 0.94, (max.y - min.y + 160) / 0.73, 420) * 1.04
  return { position: { x: lookAt.x - distance * 0.14, y: lookAt.y + distance * 0.18, z: lookAt.z + (max.z - min.z) / 2 + distance * 0.97 }, lookAt }
}

export type Vec = { x: number; y: number; z: number }

/** The camera after a key: turned about the point it looks at, moved nearer or further, or
 *  moved sideways with that point. Angles in radians; `zoom` multiplies the distance. */
export function moveCamera(position: Vec, lookAt: Vec, by: { turn?: number; tilt?: number; zoom?: number; panX?: number; panY?: number }): { position: Vec; lookAt: Vec } {
  const d = { x: position.x - lookAt.x, y: position.y - lookAt.y, z: position.z - lookAt.z }
  const distance = Math.hypot(d.x, d.y, d.z) || 1
  const theta = Math.atan2(d.x, d.z) + (by.turn ?? 0)
  // never over the top: the picture would flip
  const phi = Math.min(Math.PI - 0.15, Math.max(0.15, Math.acos(d.y / distance) + (by.tilt ?? 0)))
  const radius = Math.min(20000, Math.max(40, distance * (by.zoom ?? 1)))
  const right = { x: Math.cos(theta), z: -Math.sin(theta) }
  const target = { x: lookAt.x + right.x * (by.panX ?? 0), y: lookAt.y + (by.panY ?? 0), z: lookAt.z + right.z * (by.panX ?? 0) }
  return {
    position: { x: target.x + radius * Math.sin(phi) * Math.sin(theta), y: target.y + radius * Math.cos(phi), z: target.z + radius * Math.sin(phi) * Math.cos(theta) },
    lookAt: target,
  }
}
