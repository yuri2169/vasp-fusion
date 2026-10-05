import ForceGraph3D, { type ForceGraph3DInstance } from '3d-force-graph'
import { useEffect, useImperativeHandle, useMemo, useRef, type Ref } from 'react'
import { CanvasTexture, LinearFilter, Sprite, SpriteMaterial, SRGBColorSpace } from 'three'
import type { ElementDefinition } from 'cytoscape'
import type { FlowView, Role } from '../lib/caseGraph'
import { homeView, moveCamera, to3D, type Link3D, type Node3D, type Vec } from './flowSpace'
import { iconUri, tileLook, type ThemeColors } from './flowStyle'
import { ROLE_ICONS } from './roleIcons'

export interface Flow3DHandle {
  /** Back to where the view opened: all of it, from the front. */
  reset: () => void
  zoom: (factor: number) => void
}

export interface Flow3DProps {
  view: FlowView
  /** The same elements the 2D canvas was given: the two views cannot differ. */
  elements: readonly ElementDefinition[]
  theme: ThemeColors
  /** The node that stands for the selection, as in 2D. */
  shown: string | null
  /** A click on a node (a wallet, or a group that opens), and on nothing (null). */
  onTap: (id: string | null, context: boolean) => void
  height: number
  /** No camera move is animated. */
  still: boolean
  ref?: Ref<Flow3DHandle>
}

type GNode = Node3D & { fx: number; fy: number; fz: number }
type Graph = ForceGraph3DInstance<GNode, Link3D>

// One sprite holds a tile, the name over it and the address under it, drawn as the 2D canvas
// draws them, so a role looks the same in both views and in the legend.
const SPRITE = { w: 200, h: 124, tileY: 56, scale: 2 }

interface Look {
  fill: string
  ink: string
  stroke: string
  line: number
  dash: number[]
  double: boolean
  w: number
  h: number
}

/** The stylesheet's rules for a node (flowStyle.ts), read for one node. */
function lookOf(d: Record<string, unknown>, t: ThemeColors): Look {
  if (d.context) return { fill: t.sunk, ink: t.fg, stroke: t.data, line: 1, dash: d.kind === 'ctxmore' ? [3, 2] : [], double: false, w: d.kind === 'ctxmore' ? 30 : 12, h: d.kind === 'ctxmore' ? 15 : 12 }
  if (d.kind === 'more' || d.kind === 'fan') return { fill: t.sunk, ink: t.fg, stroke: d.kind === 'fan' ? t.chain : t.muted, line: 1, dash: [4, 3], double: false, w: 58, h: 26 }
  const role = d.role as Role
  const side = (d.side as number) ?? 28
  const base = tileLook(role, t)
  let look: Look = { fill: base.fill, ink: base.ink, stroke: t.chain, line: 1, dash: [4, 3], double: false, w: side, h: side }
  switch (d.tier) {
    case 'derived':
      look = { ...look, stroke: t.muted, line: 1.5, dash: [] }
      break
    case 'explorer_tag':
      look = { ...look, stroke: t.verifiedText, line: 2, dash: [2, 3] }
      break
    case 'curated':
      look = { ...look, stroke: t.verifiedText, line: 2, dash: [] }
      break
    case 'published_por':
      look = { ...look, stroke: t.verifiedText, line: 1.5, dash: [], double: true }
      break
  }
  if (role === 'suspect') look = { ...look, stroke: t.chain, line: 1, dash: [] }
  if (role === 'unknown') look = { ...look, stroke: t.data }
  if (role === 'hub') look = { ...look, stroke: t.data, dash: [] }
  if (role === 'mixer' || role === 'sanctioned') look = { ...look, stroke: t.fg, line: 1, dash: [] }
  if (d.named) look = { ...look, fill: t.saffron, ink: t.surface }
  return look
}

function drawTile(canvas: HTMLCanvasElement, n: Node3D, t: ThemeColors, selected: boolean, icon: HTMLImageElement | null) {
  const g = canvas.getContext('2d')
  if (!g) return
  const { w, h, tileY, scale } = SPRITE
  g.setTransform(scale, 0, 0, scale, 0, 0)
  g.clearRect(0, 0, w, h)
  const look = lookOf(n.data, t)
  const x = w / 2 - look.w / 2
  const y = tileY - look.h / 2
  if (selected) {
    g.fillStyle = t.fg
    g.globalAlpha = 0.16
    g.fillRect(x - 8, y - 8, look.w + 16, look.h + 16)
    g.globalAlpha = 1
  }
  g.fillStyle = look.fill
  g.fillRect(x, y, look.w, look.h)
  g.strokeStyle = look.stroke
  g.lineWidth = look.line
  g.setLineDash(look.dash)
  g.strokeRect(x + look.line / 2, y + look.line / 2, look.w - look.line, look.h - look.line)
  if (look.double) g.strokeRect(x + 3.5, y + 3.5, look.w - 7, look.h - 7)
  g.setLineDash([])
  if (icon && !n.data.context && n.data.kind !== 'more' && n.data.kind !== 'fan') {
    const s = look.w * 0.58
    g.drawImage(icon, w / 2 - s / 2, tileY - s / 2, s, s)
  }
  g.textAlign = 'center'
  const wide = n.data.kind === 'ctxmore'
  if (n.label) {
    g.font = n.data.context || n.data.kind === 'more' || n.data.kind === 'fan' ? '11px "Public Sans", system-ui, sans-serif' : '13px "Spline Sans Mono", ui-monospace, monospace'
    g.fillStyle = n.data.context ? (wide ? t.fg : t.data) : n.data.kind === 'more' || n.data.kind === 'fan' ? t.fg : t.muted
    g.textBaseline = wide ? 'middle' : 'top'
    n.label.split('\n').forEach((line, i) => g.fillText(line, w / 2, wide ? tileY + 1 : tileY + look.h / 2 + 5 + i * 14))
  }
  if (n.caption) {
    g.font = '700 14px Archivo, system-ui, sans-serif'
    g.textBaseline = 'bottom'
    g.fillStyle = n.threat ? t.seal : t.fg
    g.fillText(n.caption, w / 2, tileY - look.h / 2 - 6, w - 4)
  }
}

function spriteOf(n: Node3D, t: ThemeColors, selected: boolean): Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = SPRITE.w * SPRITE.scale
  canvas.height = SPRITE.h * SPRITE.scale
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.minFilter = LinearFilter
  drawTile(canvas, n, t, selected, null)
  const node = ROLE_ICONS[n.data.role as Role]
  if (node && !n.data.context) {
    const icon = new Image()
    icon.onload = () => {
      drawTile(canvas, n, t, selected, icon)
      texture.needsUpdate = true
    }
    icon.src = iconUri(node, lookOf(n.data, t).ink)
  }
  const sprite = new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthWrite: false }))
  sprite.scale.set(SPRITE.w, SPRITE.h, 1)
  // the tile's own middle sits on the wallet's point, so lines end on the tile, not on the text
  sprite.center.set(0.5, 1 - SPRITE.tileY / SPRITE.h)
  return sprite
}

const linkColour = (d: Record<string, unknown>, t: ThemeColors) =>
  d.context ? t.data : d.risk === 'high' || d.risk === 'severe' ? t.seal : d.bridge ? t.verifiedText : d.onPath ? t.chain : t.ruleStrong

/** The fund flow in space: the 2D picture's own wallets and transfers, turned. A visual aid;
 *  the 2D view is the one that is exported and replayed. Loaded only when 3D is chosen. */
export default function Flow3D({ view, elements, theme, shown, onTap, height, still, ref }: Flow3DProps) {
  const host = useRef<HTMLDivElement>(null)
  const graph = useRef<Graph | null>(null)
  const data = useMemo(() => to3D(view, elements), [view, elements])
  const home = useMemo(() => homeView(data.nodes), [data])
  const look = useRef<Vec>(home.lookAt)
  const live = useRef({ onTap, home, still })
  useEffect(() => {
    live.current = { onTap, home, still }
  })

  const place = (to: { position: Vec; lookAt: Vec }, ms = 0) => {
    look.current = to.lookAt
    graph.current?.cameraPosition(to.position, to.lookAt, live.current.still ? 0 : ms)
  }
  const nudge = (by: Parameters<typeof moveCamera>[2]) => {
    const g = graph.current
    if (!g) return
    // the mouse may have moved the point looked at since the last key
    const target = (g.controls() as { target?: Vec }).target
    if (target) look.current = { x: target.x, y: target.y, z: target.z }
    place(moveCamera(g.cameraPosition(), look.current, by))
  }
  useImperativeHandle(ref, () => ({ reset: () => place(live.current.home, 500), zoom: (factor: number) => nudge({ zoom: factor }) }))

  const first = useRef(true)

  // --- the scene, made once -----------------------------------------------------
  useEffect(() => {
    if (!host.current) return
    const g = new ForceGraph3D(host.current, { controlType: 'orbit', rendererConfig: { antialias: true, alpha: false, preserveDrawingBuffer: true } }) as unknown as Graph
    g.showNavInfo(false)
      .enableNodeDrag(false)
      // every wallet has its place: there is nothing to simulate, so nothing settles
      .warmupTicks(0)
      .cooldownTicks(0)
      .nodeRelSize(1)
      .nodeVal((n) => (((lookOf(n.data, theme).w / 2 + 2) ** 3) as number))
      .nodeThreeObjectExtend(false)
      .linkOpacity(0.85)
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalArrowLength((l) => (l.data.context ? 4 : 8))
      .linkWidth((l) => (l.data.context ? 0 : Math.max(0.6, Number(l.data.width ?? 1) * 0.55)))
      .nodeLabel((n) => (n.data.context ? `${String(n.data.name ?? n.id)} · context, not the suspect wallet's money` : `${n.caption ? `${n.caption} · ` : ''}${n.id}`))
      .linkLabel((l) => String(l.data.label || l.data.stub || '').replace('\n', ' · '))
      .onNodeClick((n) => live.current.onTap(n.id, !!n.data.context))
      .onBackgroundClick(() => live.current.onTap(null, false))
    const controls = g.controls() as { enableZoom?: boolean; enableDamping?: boolean; autoRotate?: boolean }
    // as in 2D, the wheel scrolls the page; zoom is on the buttons and the keys
    controls.enableZoom = false
    controls.autoRotate = false
    if (live.current.still) controls.enableDamping = false
    graph.current = g
    // a new scene has not been looked at yet: the first data it is given sets the camera
    first.current = true
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => host.current && g.width(host.current.clientWidth))
    observer?.observe(host.current)
    return () => {
      observer?.disconnect()
      g._destructor()
      graph.current = null
    }
    // the scene is made once; the theme and the data are applied by the effects below
  }, [])

  useEffect(() => {
    const g = graph.current
    if (!g || !host.current) return
    g.width(host.current.clientWidth).height(height)
  }, [height])

  // --- what is drawn: the same wallets and transfers as the 2D view ---------------
  useEffect(() => {
    const g = graph.current
    if (!g) return
    g.graphData({ nodes: data.nodes.map((n) => ({ ...n, fx: n.x, fy: n.y, fz: n.z })), links: data.links.map((l) => ({ ...l })) })
    if (first.current) place(home)
    first.current = false
  }, [data, home])

  useEffect(() => {
    const g = graph.current
    if (!g) return
    g.backgroundColor(theme.surface)
      .nodeThreeObject((n) => spriteOf(n, theme, n.id === shown))
      .linkColor((l) => linkColour(l.data, theme))
      .linkDirectionalArrowColor((l) => linkColour(l.data, theme))
  }, [theme, shown, data])

  return (
    <div
      ref={host}
      data-testid="flow-3d"
      role="application"
      tabIndex={0}
      aria-label="3D view of the fund flow, the same wallets and transfers as the 2D view. Arrow keys turn it, plus and minus zoom, Shift with the arrows moves it, Home puts it back. Every wallet is also listed in the Wallets tab."
      style={{ height }}
      className="w-full overflow-hidden outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--chain)]"
      onKeyDown={(e) => {
        const step = e.shiftKey ? { ArrowLeft: { panX: -40 }, ArrowRight: { panX: 40 }, ArrowUp: { panY: 40 }, ArrowDown: { panY: -40 } } : { ArrowLeft: { turn: -0.14 }, ArrowRight: { turn: 0.14 }, ArrowUp: { tilt: -0.1 }, ArrowDown: { tilt: 0.1 } }
        const by = (step as Record<string, Parameters<typeof moveCamera>[2]>)[e.key] ?? (e.key === '+' || e.key === '=' ? { zoom: 0.85 } : e.key === '-' || e.key === '_' ? { zoom: 1.18 } : null)
        if (by) {
          e.preventDefault()
          nudge(by)
        } else if (e.key === 'Home' || e.key === '0') {
          e.preventDefault()
          place(live.current.home, 500)
        }
      }}
    />
  )
}
