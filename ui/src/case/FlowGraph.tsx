import cytoscape, { type Core, type EventObject } from 'cytoscape'
import { FileCode, Image, Layers, Maximize2, Minus, Plus, Route } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { CaseDetail } from '../api/models'
import { Button } from '../components/Button'
import { TIERS } from '../components/TierTag'
import { Tip } from '../components/Tip'
import { buildFlow, clusterable, pathTo, traced, type FlowEdge, type FlowNode, type FlowView } from '../lib/caseGraph'
import { cx } from '../lib/cx'
import { downloadText, downloadUrl } from '../lib/download'
import { formatAmount, formatDateTime } from '../lib/format'
import { toGraphML } from '../lib/graphml'
import { ROLE_NAMES } from './caseText'
import { GraphLegend } from './GraphLegend'
import { readTheme, stylesheet, toElements, type ThemeColors } from './flowStyle'

/** The page's colours as the canvas needs them, read again whenever the theme changes. */
function useThemeColors(): ThemeColors {
  const [theme, setTheme] = useState(readTheme)
  useEffect(() => {
    const update = () => setTheme(readTheme())
    const observer = new MutationObserver(update)
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    media.addEventListener('change', update)
    return () => {
      observer.disconnect()
      media.removeEventListener('change', update)
    }
  }, [])
  return theme
}

/** The node that stands for a selection in this view: the wallet itself, or the group it is in. */
function shownAs(view: FlowView, selected: string | null): string | null {
  if (!selected) return null
  if (view.nodes.some((n) => n.id === selected)) return selected
  const group = view.nodes.find((n) => n.members.includes(selected))
  if (group) return group.id
  // A group was selected and the view is not grouped: its nearest wallet.
  const name = selected.startsWith('cluster:') ? selected.slice('cluster:'.length) : null
  const members = view.nodes.filter((n) => name && n.entity === name).sort((a, b) => a.column - b.column)
  return members[0]?.id ?? null
}

type Hover = { anchor: DOMRect; node?: FlowNode; edge?: FlowEdge }

const rectAt = (left: number, top: number, width: number, height: number) =>
  ({ left, top, width, height, right: left + width, bottom: top + height, x: left, y: top, toJSON: () => ({}) }) as DOMRect

const MAX_ZOOM = 1.2

/** Cytoscape draws on a 2D canvas. Where there is none, the Wallets and Transfers tabs carry the same content. */
function canDraw(): boolean {
  try {
    return !!document.createElement('canvas').getContext('2d')
  } catch {
    return false
  }
}

export interface FlowGraphProps {
  c: CaseDetail
  /** The wallet (or `cluster:<name>`) being shown; everything off its path steps back. */
  selected: string | null
  onSelect: (id: string | null) => void
  className?: string
}

/** The fund-flow graph: the Hop Rail's path on the first line, its side branches under it,
 *  funders to the left. Click a wallet to open it; every wallet is also a row in the Wallets
 *  tab, so nothing here is reachable by mouse only. */
export function FlowGraph({ c, selected, onSelect, className }: FlowGraphProps) {
  const container = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const tipId = useId()
  const theme = useThemeColors()
  const [collapse, setCollapse] = useState(false)
  const [hover, setHover] = useState<Hover | null>(null)

  const canGroup = clusterable(c)
  const view = useMemo(() => buildFlow(c, { collapse: collapse && canGroup }), [c, collapse, canGroup])
  const elements = useMemo(() => toElements(view), [view])
  const shown = shownAs(view, selected)

  // The canvas's handlers outlive a render: they read what is current through these.
  const live = useRef({ view, onSelect })
  useEffect(() => {
    live.current = { view, onSelect }
  })

  const fit = (onlyPath = false) => {
    const cy = cyRef.current
    if (!cy) return
    cy.fit(onlyPath ? cy.nodes('[onPath = 1]') : undefined, onlyPath ? 70 : 40)
    // A graph of four wallets should not be blown up to fill the frame.
    if (cy.zoom() > MAX_ZOOM) {
      cy.zoom(MAX_ZOOM)
      cy.center(onlyPath ? cy.nodes('[onPath = 1]') : undefined)
    }
  }

  const zoomBy = (factor: number) => {
    const cy = cyRef.current
    if (!cy) return
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } })
  }

  // --- the canvas, made once -------------------------------------------------
  const [drawable] = useState(canDraw)
  useEffect(() => {
    if (!container.current || !drawable) return
    const cy = cytoscape({
      container: container.current,
      layout: { name: 'preset' },
      // The wheel scrolls the page, as everywhere else; zoom is on the buttons.
      userZoomingEnabled: false,
      boxSelectionEnabled: false,
      autoungrabify: true,
      minZoom: 0.2,
      maxZoom: 3,
    })
    cyRef.current = cy

    const frame = () => container.current!.getBoundingClientRect()
    cy.on('tap', 'node', (e: EventObject) => live.current.onSelect(e.target.id()))
    cy.on('tap', (e: EventObject) => {
      if (e.target === cy) live.current.onSelect(null)
    })
    cy.on('mouseover', 'node', (e: EventObject) => {
      const node = live.current.view.nodes.find((n) => n.id === e.target.id())
      if (!node) return
      const box = e.target.renderedBoundingBox()
      const at = frame()
      e.target.addClass('hover')
      container.current!.style.cursor = 'pointer'
      setHover({ node, anchor: rectAt(at.left + box.x1, at.top + box.y1, box.x2 - box.x1, box.y2 - box.y1) })
    })
    cy.on('mouseover', 'edge', (e: EventObject) => {
      const edge = live.current.view.edges.find((x) => x.id === e.target.id())
      if (!edge) return
      const mid = e.target.renderedMidpoint()
      const at = frame()
      setHover({ edge, anchor: rectAt(at.left + mid.x - 4, at.top + mid.y - 8, 8, 16) })
    })
    const leave = (e: EventObject) => {
      e.target.removeClass('hover')
      if (container.current) container.current.style.cursor = ''
      setHover(null)
    }
    cy.on('mouseout', 'node', leave)
    cy.on('mouseout', 'edge', leave)
    cy.on('pan zoom', () => setHover(null))

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => cy.resize())
    observer?.observe(container.current)
    return () => {
      observer?.disconnect()
      cy.destroy()
      cyRef.current = null
    }
  }, [drawable])

  useEffect(() => {
    cyRef.current?.style(stylesheet(theme))
  }, [theme])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().remove()
      cy.add(elements)
    })
    fit()
  }, [elements])

  // --- the selection: its path stays, the rest steps back ---------------------
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().removeClass('dim sel')
      if (!shown) return
      const path = pathTo(view, shown)
      cy.elements().forEach((el) => {
        const id = el.data('owner') ?? el.id()
        if (!path.nodes.has(id) && !path.edges.has(id)) el.addClass('dim')
      })
      cy.getElementById(shown).addClass('sel')
    })
  }, [view, elements, shown])

  const rows = view.nodes.reduce((max, n) => Math.max(max, n.row), 0) + 1
  const height = Math.min(600, Math.max(340, rows * 92 + 110))
  const transfers = view.edges.reduce((n, e) => n + e.transfers.length, 0)
  const wallets = view.nodes.reduce((n, node) => n + node.members.length, 0)

  return (
    <section aria-labelledby={`${tipId}-title`} className={cx('rounded-md border border-rule bg-surface', className)}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-rule px-4 py-2">
        <h2 id={`${tipId}-title`} className="eyebrow">
          Fund flow
        </h2>
        <div className="flex flex-wrap items-center gap-1">
          <Button size="sm" variant="ghost" icon={<Maximize2 size={13} aria-hidden />} onClick={() => fit()}>
            Fit
          </Button>
          <Button size="sm" variant="ghost" icon={<Route size={13} aria-hidden />} onClick={() => fit(true)}>
            Focus path
          </Button>
          <Button size="sm" variant="ghost" aria-label="Zoom in" title="Zoom in" onClick={() => zoomBy(1.25)} icon={<Plus size={13} aria-hidden />} />
          <Button size="sm" variant="ghost" aria-label="Zoom out" title="Zoom out" onClick={() => zoomBy(0.8)} icon={<Minus size={13} aria-hidden />} />
          {canGroup && (
            <Button
              size="sm"
              variant={collapse ? 'secondary' : 'ghost'}
              aria-pressed={collapse}
              icon={<Layers size={13} aria-hidden />}
              onClick={() => setCollapse((v) => !v)}
            >
              Group exchange wallets
            </Button>
          )}
          <span aria-hidden className="mx-1 h-4 w-px bg-rule" />
          <Button
            size="sm"
            variant="ghost"
            icon={<Image size={13} aria-hidden />}
            onClick={() => {
              const cy = cyRef.current
              if (cy) downloadUrl(`case-${c.id}-graph.png`, cy.png({ full: true, scale: 2, bg: theme.surface, output: 'base64uri' }))
            }}
          >
            Export PNG
          </Button>
          <Button
            size="sm"
            variant="ghost"
            icon={<FileCode size={13} aria-hidden />}
            onClick={() => downloadText(`case-${c.id}.graphml`, toGraphML(c), 'application/graphml+xml')}
          >
            Export GraphML
          </Button>
        </div>
      </div>

      <div
        ref={container}
        role="img"
        aria-label={`Fund-flow graph: ${wallets} wallets and ${transfers} transfers, left to right by hop. Every wallet is also listed in the Wallets tab.`}
        style={{ height: drawable ? height : undefined }}
        className="w-full"
      />
      {!drawable && (
        <p className="px-4 py-6 text-sm text-muted">
          This browser cannot draw the graph. The Wallets and Transfers tabs list everything it would show.
        </p>
      )}

      <GraphLegend view={view} named={c.top_vasp} />

      <Tip id={tipId} anchor={hover?.anchor ?? null}>
        {hover?.node && <NodeCard node={hover.node} />}
        {hover?.edge && <EdgeCard edge={hover.edge} asset={view.asset} />}
      </Tip>
    </section>
  )
}

function NodeCard({ node }: { node: FlowNode }) {
  return (
    <>
      {node.kind === 'cluster' ? (
        <span className="block font-medium">
          {node.entity} · {node.members.length} wallets
        </span>
      ) : (
        <span className="block break-all font-mono">{node.id}</span>
      )}
      <span className="mt-1 block text-muted">
        {ROLE_NAMES[node.role]}
        {node.entity && node.kind === 'wallet' && (
          <>
            {' · '}
            <span className="font-medium text-fg">{node.entity}</span>
          </>
        )}
        {' · '}
        {TIERS[node.tier ?? 'none'].name}
      </span>
      <span className="mt-1 block text-muted">Click to open it in the side panel</span>
    </>
  )
}

const LISTED = 4

function EdgeCard({ edge, asset }: { edge: FlowEdge; asset: string }) {
  const many = edge.transfers.length > 1
  return (
    <>
      <span className="tabular block font-mono font-medium">
        {many && <span className="font-sans">{edge.transfers.length} transfers · </span>}
        {formatAmount(edge.amount, asset)}
      </span>
      {edge.transfers.slice(0, LISTED).map((t) => (
        <span key={t.id} className="mt-1.5 block">
          <span className="tabular block font-mono text-muted">
            {many && `${formatAmount(traced(t), t.asset)} · `}
            {formatDateTime(t.block_time)}
            {traced(t) !== t.amount && ` · part of a transfer of ${formatAmount(t.amount, t.asset)}`}
          </span>
          <span className="block break-all font-mono">{t.tx_hash}</span>
        </span>
      ))}
      {edge.transfers.length > LISTED && (
        <span className="mt-1.5 block text-muted">and {edge.transfers.length - LISTED} more, in the Transfers tab</span>
      )}
    </>
  )
}
