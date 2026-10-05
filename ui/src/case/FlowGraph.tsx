import cytoscape, { type Core, type EventObject } from 'cytoscape'
import { Box, ChevronLeft, ChevronRight, Eye, EyeOff, FileCode, Image, Layers, Maximize2, Minus, Pause, Play, Plus, Route, RotateCcw } from 'lucide-react'
import { lazy, Suspense, useEffect, useId, useMemo, useRef, useState } from 'react'
import { api } from '../api/api'
import type { CaseContext, CaseDetail, ContextEdge, FlowRisk } from '../api/models'
import { Button } from '../components/Button'
import { TIERS } from '../components/TierTag'
import { Tip } from '../components/Tip'
import { BIG_GRAPH, buildFlow, clusterable, FAN_KEEP, focusOf, foldFlow, pathTo, traced, type FlowEdge, type FlowNode, type FlowView } from '../lib/caseGraph'
import { CONTEXT_KEEP, CONTEXT_MORE, mergeContext, withContext } from '../lib/context'
import { cx } from '../lib/cx'
import { downloadText, downloadUrl } from '../lib/download'
import { formatAmount, formatDateTime, truncateMiddle } from '../lib/format'
import { count, plural } from '../overview/words'
import { toGraphML } from '../lib/graphml'
import { replaySteps, shownAt, type ReplayStep } from '../lib/replay'
import { ROLE_NAMES } from './caseText'
import { GraphLegend } from './GraphLegend'
import { TraceSummaryLine } from './TraceSummaryLine'
import { RISK_WORDS } from '../components/RiskTag'
import { captionY, edgeRisk, fanWords, readTheme, stylesheet, toElements, type ThemeColors } from './flowStyle'
import type { Flow3DHandle } from './Flow3D'

// The 3D library (three.js) is large and most officers never open it: it is fetched when
// 3D is chosen, from this installation like everything else.
const Flow3D = lazy(() => import('./Flow3D'))

/** The 3D view draws with WebGL. Where there is none the switch says so and 2D stays. */
function canWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return !!(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}

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

/** A large graph (over BIG_GRAPH wallets): this many wallets a hop are drawn besides the path,
 *  and a hop's fold gives up this many more each time it is asked. */
const PER_HOP = 12
const MORE = 50
const hopName = (column: number) => (column < 0 ? 'the funders' : `hop ${column}`)

/** One transfer of the replay is on screen this long before the next. */
const STEP_MS = 750
const DRAW_MS = 520

const reducedMotion = () => typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Never drawn larger than life: the type on the canvas is then 14, as on the page. */
const MAX_ZOOM = 1

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
  /** Where context is read from: all of a case's (wallet null), or one wallet's. The API by default. */
  loadContext?: (caseId: string, wallet: string | null) => Promise<CaseContext>
}

const readContext = (caseId: string, wallet: string | null) => api.caseContext(caseId, wallet)
/** The whole context of a case, as a key beside the wallets'. */
const ALL = ''

/** The fund-flow graph: the Hop Rail's path on the first line, its side branches under it,
 *  funders to the left. Click a wallet to open it; drag one to move it out of the way (it
 *  stays there until Reset layout). The replay draws the transfers in the order they
 *  happened. Every wallet is also a row in the Wallets tab, and every transfer a row in the
 *  Transfers tab, so nothing here is reachable by mouse only. */
export function FlowGraph({ c, selected, onSelect, className, loadContext = readContext }: FlowGraphProps) {
  const container = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const tipId = useId()
  const theme = useThemeColors()
  // 2D is the view of record (pictures, replay, the case file). 3D is the same picture, turned.
  const [mode, setMode] = useState<'2d' | '3d'>('2d')
  const [gl] = useState(canWebGL)
  const space = useRef<Flow3DHandle>(null)
  const in3d = mode === '3d'
  const big = c.graph.nodes.length > BIG_GRAPH
  const [collapse, setCollapse] = useState(big)
  const [hover, setHover] = useState<Hover | null>(null)
  // A large graph: how many hops are drawn (null = as far as the Hop Rail's path goes, 2 at
  // least), and the hops the officer asked to see more wallets of.
  const [hops, setHops] = useState<number | null>(null)
  const [opened, setOpened] = useState<ReadonlyMap<number, number>>(new Map())

  // The fans the officer opened: the wallets of each are drawn one by one until it is collapsed.
  const [openFans, setOpenFans] = useState<ReadonlySet<string>>(new Set())
  const openFan = (id: string) => setOpenFans((was) => new Set(was).add(id))
  const closeFan = (id: string) => setOpenFans((was) => new Set([...was].filter((x) => x !== id)))

  const canGroup = clusterable(c)
  const full = useMemo(() => buildFlow(c, { collapse: collapse && canGroup, openFans }), [c, collapse, canGroup, openFans])
  const pathEnds = useMemo(() => full.nodes.reduce((max, n) => (n.onPath ? Math.max(max, n.column) : max), 2), [full])
  const folded = useMemo(() => {
    if (!big) return null
    // The wallet being looked at, and the way to it, are drawn whatever their size.
    const at = selected ? (shownAs(full, selected) ?? selected) : null
    const keep = at ? pathTo(full, at).nodes : undefined
    // A wallet picked from the Wallets tab may sit past the hops drawn: draw as far as it is.
    const reach = Math.abs(full.nodes.find((n) => n.id === at)?.column ?? 0)
    return foldFlow(full, { perColumn: PER_HOP, maxHop: Math.max(hops ?? pathEnds, reach), keep, shown: opened })
  }, [big, full, hops, pathEnds, opened, selected])
  const trail: FlowView = folded ?? full

  // --- context: the other transfers of the wallets the trace read. Off until asked for, drawn
  // greyed, and never part of the answer. `asked` is what the officer switched on (the whole
  // context, or wallets one by one); `answers` is what came back for each.
  const [asked, setAsked] = useState<ReadonlySet<string>>(new Set())
  const [answers, setAnswers] = useState<ReadonlyMap<string, CaseContext | Error>>(new Map())
  const [contextShown, setContextShown] = useState<ReadonlyMap<string, number>>(new Map())
  const ask = (key: string) => {
    setAsked((was) => new Set(was).add(key))
    if (answers.has(key)) return
    loadContext(c.id, key === ALL ? null : key).then(
      (got) => setAnswers((was) => new Map(was).set(key, got)),
      (err: unknown) => setAnswers((was) => new Map(was).set(key, err instanceof Error ? err : new Error(String(err)))),
    )
  }
  const unask = (key: string) => setAsked((was) => new Set([...was].filter((k) => k !== key)))
  /** Back to the default view, exactly: nothing of the context stays on the picture. */
  const hideContext = () => {
    setAsked(new Set())
    setContextShown(new Map())
  }
  const openContextMore = (id: string) => setContextShown((was) => new Map(was).set(id, (was.get(id) ?? CONTEXT_KEEP) + CONTEXT_MORE))
  const got = useMemo(() => [...asked].map((key) => answers.get(key)).filter((a): a is CaseContext => !!a && !(a instanceof Error)), [asked, answers])
  const withCtx = useMemo(() => (got.length > 0 ? withContext(trail, mergeContext(got), { shown: contextShown }) : null), [trail, got, contextShown])
  const view: FlowView = withCtx ?? trail
  const waiting = [...asked].some((key) => !answers.has(key))
  const adds = c.trace_summary ? c.trace_summary.transfers_seen - c.trace_summary.transfers_followed : null
  // The wallet being shown, when it is a wallet of the case and not a group of them.
  const wallet = selected && c.graph.nodes.some((n) => n.id === selected) ? selected : null

  const flows = useMemo(() => new Map((c.risk?.flows ?? []).map((f) => [f.edge_id, f])), [c.risk])
  const elements = useMemo(() => toElements(view, flows), [view, flows])
  const shown = shownAs(view, selected)

  // --- the replay: transfers in the order they happened -----------------------
  const steps = useMemo(() => replaySteps(view), [view])
  const [still] = useState(reducedMotion)
  // How many transfers are drawn. All of them, unless the officer is replaying.
  // It belongs to one picture: another case, a grouping or an opened hop starts it over.
  const [replay, setReplay] = useState<{ shape: string; at: number | null; play: boolean }>({ shape: '', at: null, play: false })
  const shape = `${c.id}|${c.graph.nodes.length}|${collapse}|${hops}|${[...opened].join()}|${[...openFans].join()}|${got.length}|${[...contextShown].join()}`
  const fitted = useRef<string | null>(null)

  const mine = replay.shape === shape
  const now = Math.min((mine ? replay.at : null) ?? steps.length, steps.length)
  const playing = mine && replay.play && now < steps.length
  const setAt = (at: number, play = false) => setReplay({ shape, at, play })
  const step = (by: number) => setAt(Math.max(0, Math.min(steps.length, now + by)))
  const toggle = () => {
    if (still) step(1)
    else if (playing) setAt(now)
    else setAt(now >= steps.length ? 0 : now, true)
  }

  // Where the officer dragged a wallet to. Kept while this case is open; a redraw puts each
  // one back where it was left.
  const moved = useRef({ id: c.id, at: new Map<string, { x: number; y: number }>() })

  const openMore = (column: number) => setOpened((was) => new Map(was).set(column, (was.get(column) ?? PER_HOP) + MORE))

  // The canvas's handlers outlive a render: they read what is current through these.
  /** A click on a node, in either view (null: on nothing). */
  const tap = (id: string | null) => {
    if (id === null) onSelect(null)
    // The rest of a hop is not a wallet to open: a click draws more of that hop.
    else if (id.startsWith('more:')) openMore(Number(id.slice('more:'.length)))
    // nor is a fan's group: a click draws its wallets one by one, in place
    else if (id.startsWith('fan:')) openFan(id)
    // the rest of a wallet's context: a click draws more of it
    else if (id.startsWith('ctxmore:')) openContextMore(id)
    else onSelect(id)
  }
  const live = useRef({ view, tap })
  useEffect(() => {
    live.current = { view, tap }
  })

  // Back in 2D the canvas has been hidden: it takes its size again and shows all of the picture.
  useEffect(() => {
    if (in3d) return
    cyRef.current?.resize()
    if (cyRef.current && fitted.current !== null) fit()
    // only on a change of view
  }, [in3d])

  const fit = (onlyPath = false) => {
    const cy = cyRef.current
    if (!cy) return
    cy.fit(onlyPath ? cy.nodes('[onPath = 1]') : undefined, onlyPath ? 70 : 32)
    // A graph of four wallets should not be blown up to fill the frame.
    if (cy.zoom() > MAX_ZOOM) {
      cy.zoom(MAX_ZOOM)
      cy.center(onlyPath ? cy.nodes('[onPath = 1]') : undefined)
    }
  }

  /** Every wallet back where the layout put it. */
  const resetLayout = () => {
    const cy = cyRef.current
    moved.current.at.clear()
    if (!cy) return
    cy.batch(() => {
      for (const el of elements) if (el.group === 'nodes' && el.position) cy.getElementById(el.data.id!).position({ ...el.position })
    })
    fit()
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
      // A wallet can be dragged out of the way. A drag is not a click: Cytoscape sends
      // `tap` only when the pointer did not move.
      autoungrabify: false,
      // A large graph is moved as one picture and redrawn when the drag ends; a small one is
      // redrawn every frame, which is sharper and costs nothing at that size.
      textureOnViewport: big,
      minZoom: 0.2,
      maxZoom: 3,
    })
    cyRef.current = cy
    // a new canvas has not been fitted, whatever the last one was
    fitted.current = null
    // For the scripts that drive the page in a real browser (ui/scripts): where a wallet is drawn.
    ;(window as { __flowCy?: Core }).__flowCy = cy

    const frame = () => container.current!.getBoundingClientRect()
    cy.on('tap', 'node', (e: EventObject) => {
      // a wallet that is only context is not a wallet of the case: a click names it, no more
      if (e.target.data('context') && !String(e.target.id()).startsWith('ctxmore:')) e.target.toggleClass('named')
      else live.current.tap(e.target.id())
    })
    cy.on('tap', (e: EventObject) => {
      if (e.target === cy) live.current.tap(null)
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
    cy.on('grab drag', 'node', () => {
      setHover(null)
      if (container.current) container.current.style.cursor = 'grabbing'
    })
    // The name over a wallet goes where the wallet goes.
    cy.on('position', 'node', (e: EventObject) => {
      const id: string = e.target.id()
      if (id.startsWith('caption:')) return
      const caption = cy.getElementById(`caption:${id}`)
      if (!caption.nonempty()) return
      const { x, y } = e.target.position()
      caption.position({ x, y: captionY(y, e.target.data('side') ?? 0) })
    })
    cy.on('dragfree', 'node', (e: EventObject) => {
      const { x, y } = e.target.position()
      moved.current.at.set(e.target.id(), { x, y })
      if (container.current) container.current.style.cursor = ''
    })

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => cy.resize())
    observer?.observe(container.current)
    return () => {
      observer?.disconnect()
      cy.destroy()
      cyRef.current = null
      delete (window as { __flowCy?: Core }).__flowCy
    }
  }, [drawable, big])

  useEffect(() => {
    cyRef.current?.style(stylesheet(theme))
  }, [theme])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().remove()
      // Copies: Cytoscape keeps the position object it is given and moves it on a drag, and
      // the layout's own positions are what Reset layout goes back to.
      cy.add(elements.map((el) => (el.position ? { ...el, position: { ...el.position } } : el)))
      // A wallet that was dragged stays where it was put; nothing here refits for it.
      if (moved.current.id !== c.id) moved.current = { id: c.id, at: new Map() }
      for (const [id, at] of moved.current.at) {
        const node = cy.getElementById(id)
        if (node.nonempty()) node.position(at)
      }
    })
    // Fit when the picture is a different one (another case, grouped, a hop opened), not when a
    // selection in a large graph only brought one more wallet into it: the officer's place stays.
    if (fitted.current !== shape) {
      fit()
      fitted.current = shape
    }
  }, [elements, shape, c.id])

  // --- the selection: its path stays, the rest steps back ---------------------
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().removeClass('dim sel')
      if (!shown) return
      cy.getElementById(shown).addClass('sel')
      const focus = focusOf(view, shown)
      if (!focus) return
      cy.elements().forEach((el) => {
        const id = el.data('owner') ?? el.id()
        if (!focus.nodes.has(id) && !focus.edges.has(id)) el.addClass('dim')
      })
    })
  }, [view, elements, shown])

  // --- the replay on the canvas: what has not moved yet is not drawn -----------
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.elements().removeClass('ahead')
      if (now >= steps.length) return
      const on = shownAt(view, steps, now)
      cy.elements().forEach((el) => {
        const id = el.data('owner') ?? el.id()
        if (!on.nodes.has(id) && !on.edges.has(id)) el.addClass('ahead')
      })
    })
  }, [view, elements, steps, now])

  // The transfer that has just been added draws in, and its amount counts up to what it was.
  // With reduced motion, or on a step back, it is simply there.
  const last = useRef(now)
  useEffect(() => {
    const cy = cyRef.current
    const forward = now === last.current + 1
    last.current = now
    if (!cy || still || !forward || now < 1) return
    return drawIn(cy, steps[now - 1])
  }, [steps, now, still])

  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => setReplay((r) => ({ ...r, at: now + 1 })), STEP_MS)
    return () => window.clearTimeout(timer)
  }, [playing, now])

  const current = now > 0 ? steps[now - 1] : null
  const said = current
    ? `Transfer ${now} of ${steps.length}: ${formatAmount(current.amount, current.asset)}${current.time ? `, ${formatDateTime(current.time)}` : ''}`
    : `Before the first of ${plural(steps.length, 'transfer')}`

  const rows = view.nodes.reduce((max, n) => Math.max(max, n.row), 0) - view.nodes.reduce((min, n) => Math.min(min, n.row), 0) + 1
  const height = Math.min(640, Math.max(320, rows * 90 + 96))
  // what the picture says of itself counts the trail only; context is said separately
  const transfers = trail.edges.reduce((n, e) => n + e.transfers.length, 0)
  const wallets = trail.nodes.reduce((n, node) => n + node.members.length, 0)
  const drawn = trail.nodes.reduce((n, node) => n + (node.kind === 'more' ? 0 : node.members.length), 0)
  const onGraph = useMemo(() => new Set(c.graph.nodes.map((n) => n.id)), [c])
  const contextNotes = [...asked].flatMap((key) => {
    const a = answers.get(key)
    if (!a) return []
    if (a instanceof Error) return [a.message]
    if (!a.recorded) return [a.text]
    return [a.truncated ? `${a.text} The first ${count(a.edges.length)} of ${count(a.transfers)} are drawn.` : a.text]
  })

  return (
    <section aria-labelledby={`${tipId}-title`} className={cx('panel', className)}>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-rule px-4 py-2">
        <h2 id={`${tipId}-title`} className="eyebrow">
          Fund flow
        </h2>
        <div className="flex flex-wrap items-center gap-1">
          <fieldset className="mr-1 flex items-center border border-rule" aria-describedby={gl ? undefined : `${tipId}-nogl`}>
            <legend className="sr-only">View</legend>
            {(['2d', '3d'] as const).map((m) => (
              <label
                key={m}
                className={cx(
                  'flex cursor-pointer items-center gap-1 px-2 py-1 text-sm has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-1 has-[:focus-visible]:outline-[var(--chain)]',
                  mode === m ? 'bg-sunk font-semibold text-fg' : 'text-muted',
                  m === '3d' && !gl && 'cursor-not-allowed opacity-60',
                )}
              >
                <input type="radio" name={`${tipId}-view`} value={m} checked={mode === m} disabled={m === '3d' && (!gl || !drawable)} onChange={() => setMode(m)} className="sr-only" />
                {m === '3d' && <Box size={13} aria-hidden />}
                {m === '2d' ? '2D' : '3D'}
              </label>
            ))}
          </fieldset>
          {in3d ? (
            <Button size="sm" variant="ghost" icon={<RotateCcw size={13} aria-hidden />} title="Turn the view back to where it opened (Home)" onClick={() => space.current?.reset()}>
              Reset view
            </Button>
          ) : (
            <>
              <Button size="sm" variant="ghost" icon={<Maximize2 size={13} aria-hidden />} onClick={() => fit()}>
                Fit
              </Button>
              <Button size="sm" variant="ghost" icon={<RotateCcw size={13} aria-hidden />} title="Put every wallet back where the layout drew it" onClick={resetLayout}>
                Reset layout
              </Button>
              <Button size="sm" variant="ghost" icon={<Route size={13} aria-hidden />} onClick={() => fit(true)}>
                Focus path
              </Button>
            </>
          )}
          <Button size="sm" variant="ghost" aria-label="Zoom in" title="Zoom in" onClick={() => (in3d ? space.current?.zoom(0.8) : zoomBy(1.25))} icon={<Plus size={13} aria-hidden />} />
          <Button size="sm" variant="ghost" aria-label="Zoom out" title="Zoom out" onClick={() => (in3d ? space.current?.zoom(1.25) : zoomBy(0.8))} icon={<Minus size={13} aria-hidden />} />
          {canGroup && (
            <Button
              size="sm"
              variant={collapse ? 'secondary' : 'ghost'}
              aria-pressed={collapse}
              aria-label="Group exchange wallets"
              title="Draw the wallets of one exchange as one node"
              icon={<Layers size={13} aria-hidden />}
              onClick={() => setCollapse((v) => !v)}
            >
              Group
            </Button>
          )}
          <span aria-hidden className="mx-1 h-4 w-px bg-rule" />
          <Button
            size="sm"
            variant="ghost"
            aria-label="Export PNG"
            disabled={in3d}
            title={in3d ? 'The picture for the file comes from the 2D view' : 'Save the picture as a PNG'}
            icon={<Image size={13} aria-hidden />}
            onClick={() => {
              const cy = cyRef.current
              if (cy) downloadUrl(`case-${c.id}-graph.png`, cy.png({ full: true, scale: 2, bg: theme.surface, output: 'base64uri' }))
            }}
          >
            PNG
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Export GraphML"
            title="Save the graph as GraphML (Gephi, yEd, Maltego)"
            icon={<FileCode size={13} aria-hidden />}
            onClick={() => downloadText(`case-${c.id}.graphml`, toGraphML(c), 'application/graphml+xml')}
          >
            GraphML
          </Button>
        </div>
      </div>

      {!gl && (
        <p id={`${tipId}-nogl`} className="border-b border-rule px-4 py-1.5 text-sm text-muted">
          The 3D view needs WebGL, which this browser does not offer here. The 2D view shows the same wallets and transfers.
        </p>
      )}
      {in3d && (
        <p className="border-b border-rule bg-sunk px-4 py-1.5 text-sm text-muted" data-testid="note-3d">
          3D is a visual aid: the same wallets and transfers, turned. It has no PNG export and no replay; pictures for the file come from the 2D view. Drag to turn it, Shift and drag to
          move it; the arrow keys, + and − do the same once the view has the focus.
        </p>
      )}

      {drawable && !in3d && steps.length > 1 && (
        <div
          role="group"
          aria-label="Replay the money"
          className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule px-4 py-1.5"
          onKeyDown={(e) => {
            const on = e.target as HTMLElement
            if (e.key === ' ' && on.tagName !== 'BUTTON') {
              e.preventDefault()
              toggle()
            } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && on.tagName !== 'INPUT') {
              e.preventDefault()
              step(e.key === 'ArrowRight' ? 1 : -1)
            }
          }}
        >
          <span className="colhead">Replay</span>
          <div className="flex items-center gap-1">
            {!still && (
              <Button
                size="sm"
                variant={playing ? 'secondary' : 'ghost'}
                aria-label={playing ? 'Pause the replay' : 'Play the transfers in the order they happened'}
                title={playing ? 'Pause (space)' : 'Play the transfers in the order they happened (space)'}
                icon={playing ? <Pause size={13} aria-hidden /> : <Play size={13} aria-hidden />}
                onClick={toggle}
              >
                {playing ? 'Pause' : 'Play'}
              </Button>
            )}
            <Button size="sm" variant="ghost" aria-label="Previous transfer" title="Previous transfer (left arrow)" disabled={now <= 0} icon={<ChevronLeft size={13} aria-hidden />} onClick={() => step(-1)} />
            <Button size="sm" variant="ghost" aria-label="Next transfer" title="Next transfer (right arrow)" disabled={now >= steps.length} icon={<ChevronRight size={13} aria-hidden />} onClick={() => step(1)} />
          </div>
          <input
            type="range"
            aria-label="Transfers drawn, in time order"
            aria-valuetext={said}
            min={0}
            max={steps.length}
            step={1}
            value={now}
            onChange={(e) => setAt(Number(e.target.value))}
            className="h-1 min-w-[8rem] flex-1 cursor-pointer accent-[var(--chain)]"
          />
          <p className="tabular min-w-[18rem] text-sm text-muted" data-testid="replay-now">
            {current ? (
              <>
                Transfer <span className="font-mono text-fg">{now}</span> of <span className="font-mono text-fg">{steps.length}</span>
                {' · '}
                <span className="font-mono text-fg">{formatAmount(current.amount, current.asset)}</span>
                {current.time && ` · ${formatDateTime(current.time)}`}
              </>
            ) : (
              said
            )}
          </p>
        </div>
      )}

      {folded && (
        <div role="group" aria-label="Parts of the graph not drawn" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule bg-sunk px-4 py-2 text-sm text-muted">
          <p className="mr-auto">
            Drawing {plural(drawn, 'wallet')} of {c.graph.nodes.length.toLocaleString('en-US')}: the path, then {PER_HOP} of each hop (labelled wallets first,
            then the largest). Every wallet and transfer is in the tabs below.
          </p>
          {folded.folded.map(({ column, wallets: left }) => (
            <Button key={column} size="sm" variant="ghost" onClick={() => openMore(column)}>
              Draw {Math.min(MORE, left)} more of {hopName(column)} ({left.toLocaleString('en-US')} folded)
            </Button>
          ))}
          {folded.beyond && (
            <Button size="sm" variant="secondary" onClick={() => setHops(folded.beyond!.hop)}>
              Draw hop {folded.beyond.hop} ({plural(folded.beyond.wallets, 'wallet')} from there on)
            </Button>
          )}
        </div>
      )}

      {c.trace_summary && <TraceSummaryLine summary={c.trace_summary} chain={c.chain} onGraph={onGraph} selected={selected} onSelect={onSelect} />}

      {drawable && (c.trace_summary || asked.size > 0) && (
        <div role="group" aria-label="Context: other transfers" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule px-4 py-1.5 text-sm text-muted">
          <span className="colhead">Context</span>
          <Button
            size="sm"
            variant={asked.has(ALL) ? 'secondary' : 'ghost'}
            role="switch"
            aria-checked={asked.has(ALL)}
            icon={<Eye size={13} aria-hidden />}
            title="Draw, greyed, every other transfer of the wallets this trace read"
            onClick={() => (asked.has(ALL) ? unask(ALL) : ask(ALL))}
          >
            Show all context{adds != null && !asked.has(ALL) ? ` (adds ${plural(adds, 'transfer')})` : ''}
          </Button>
          {wallet && (
            <Button size="sm" variant={asked.has(wallet) ? 'secondary' : 'ghost'} aria-pressed={asked.has(wallet)} onClick={() => (asked.has(wallet) ? unask(wallet) : ask(wallet))}>
              {asked.has(wallet) ? 'Hide this wallet\u2019s other transfers' : 'Show this wallet\u2019s other transfers'}
            </Button>
          )}
          {asked.size > 0 && (
            <Button size="sm" variant="ghost" icon={<EyeOff size={13} aria-hidden />} onClick={hideContext}>
              Hide context
            </Button>
          )}
          <p role="status" className="basis-full empty:hidden sm:basis-auto">
            {waiting ? 'Reading the other transfers\u2026' : contextNotes.join(' ')}
            {!waiting && withCtx && withCtx.contextHidden > 0 ? ` ${plural(withCtx.contextHidden, 'transfer')} between wallets that are not drawn ${withCtx.contextHidden === 1 ? 'is' : 'are'} left out.` : ''}
          </p>
        </div>
      )}

      {openFans.size > 0 && (
        <div role="group" aria-label="Opened groups of wallets" className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-rule bg-sunk px-4 py-2 text-sm text-muted">
          {[...openFans].map((id) => {
            const [, side, of] = id.split(/:(in|out):/)
            const whose = of === c.address ? 'the suspect wallet' : truncateMiddle(of, 6, 4)
            return (
              <span key={id} className="flex items-center gap-2">
                {side === 'in' ? `Every wallet that paid ${whose} is drawn.` : `Every wallet ${whose} paid is drawn.`}
                <Button size="sm" variant="secondary" aria-label={side === 'in' ? `Collapse the wallets that paid ${whose}` : `Collapse the wallets ${whose} paid`} onClick={() => closeFan(id)}>
                  Collapse
                </Button>
              </span>
            )
          })}
        </div>
      )}

      <div
        ref={container}
        role="img"
        aria-label={
          folded
            ? `Fund-flow graph: ${drawn} of ${c.graph.nodes.length} wallets drawn, left to right by hop. Every wallet is listed in the Wallets tab.`
            : `Fund-flow graph: ${wallets} wallets and ${transfers} transfers, left to right by hop. Every wallet is also listed in the Wallets tab.${withCtx ? ` ${withCtx.contextTransfers} other transfers are drawn greyed as context; they are not the suspect wallet's money.` : ''}`
        }
        style={{ height: drawable ? height : undefined }}
        className={cx('w-full', in3d && 'hidden')}
      />
      {in3d && (
        <Suspense fallback={<p role="status" className="px-4 py-6 text-base text-muted" style={{ minHeight: height }}>Loading the 3D view…</p>}>
          <Flow3D ref={space} view={view} elements={elements} theme={theme} shown={shown} onTap={(id) => tap(id)} height={height} still={still} />
        </Suspense>
      )}
      {!drawable && (
        <p className="px-4 py-6 text-base text-muted">
          This browser cannot draw the graph. The Wallets and Transfers tabs list everything it would show.
        </p>
      )}

      <GraphLegend view={view} named={c.top_vasp} flagged={flows.size > 0} />

      <Tip id={tipId} anchor={hover?.anchor ?? null}>
        {hover?.node && <NodeCard node={hover.node} />}
        {hover?.edge && <EdgeCard edge={hover.edge} flows={flows} />}
      </Tip>
    </section>
  )
}

/** Draw one transfer in: the line runs from payer to payee and the amount on it counts up.
 *  Whatever happens (the end, a pause, another step), the line and the amount are left
 *  exactly as the stylesheet and the data have them. Returns the way to stop early. */
function drawIn(cy: Core, step: ReplayStep): () => void {
  const edge = cy.getElementById(step.edge)
  if (!edge.nonempty()) return () => {}
  const real: string = edge.data('label')
  const a = edge.source().position()
  const b = edge.target().position()
  const length = Math.max(1, Math.hypot(b.x - a.x, b.y - a.y))
  const started = performance.now()
  let frame = 0
  let done = false
  const settle = () => {
    if (done) return
    done = true
    cancelAnimationFrame(frame)
    edge.stop(true, false)
    edge.removeStyle()
    edge.data('label', real)
  }
  edge.style({ 'line-style': 'dashed', 'line-dash-pattern': [length, length], 'line-dash-offset': length, 'target-arrow-shape': 'none' })
  edge.animate({ style: { 'line-dash-offset': 0 } }, { duration: DRAW_MS, easing: 'ease-out', complete: settle })
  const tick = () => {
    if (done) return
    const part = Math.min(1, (performance.now() - started) / DRAW_MS)
    if (part >= 1) return settle()
    if (real) edge.data('label', formatAmount(step.amount * part, step.asset))
    frame = requestAnimationFrame(tick)
  }
  if (real) frame = requestAnimationFrame(tick)
  return settle
}

function NodeCard({ node }: { node: FlowNode }) {
  if (node.context)
    return (
      <>
        {node.kind === 'ctxmore' ? (
          <span className="block font-medium">{count(node.members.length)} other wallets</span>
        ) : (
          <span className="block break-all font-mono">{node.id}</span>
        )}
        <span className="mt-1 block text-muted">
          Context: {node.kind === 'ctxmore' ? 'they are' : 'it is'} on other transfers of a wallet on the trail. None of the suspect wallet&rsquo;s money was traced to {node.kind === 'ctxmore' ? 'them' : 'it'}.
          {node.entity && (
            <>
              {' '}
              Labelled <span className="font-medium text-fg">{node.entity}</span>.
            </>
          )}
        </span>
        {node.kind === 'ctxmore' && <span className="mt-1 block text-muted">Click to draw {Math.min(CONTEXT_MORE, node.members.length)} more.</span>}
      </>
    )
  if (node.kind === 'more')
    return (
      <>
        <span className="block font-medium">
          {count(node.members.length)} more {node.members.length === 1 ? 'wallet' : 'wallets'} at {hopName(node.column)}
        </span>
        <span className="mt-1 block text-muted">Not drawn one by one. Labelled wallets and the largest of the hop are.</span>
        <span className="mt-1 block text-muted">Click to draw {Math.min(MORE, node.members.length)} more. All are in the Wallets tab.</span>
      </>
    )
  if (node.kind === 'fan')
    return (
      <>
        <span className="block font-medium">{fanWords(node)}</span>
        <span className="mt-1 block text-muted">
          Unlabelled wallets that only {node.fan?.side === 'out' ? 'received from' : 'paid'} this one wallet. The largest {FAN_KEEP} are drawn beside it.
        </span>
        <span className="mt-1 block text-muted">Click to draw every one. All are in the Wallets tab.</span>
      </>
    )
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
      <span className="mt-1 block text-muted">Click to open it in the side panel. Drag to move it.</span>
    </>
  )
}

const LISTED = 4

const WHY: Record<ContextEdge['why'], string> = {
  dust: 'below the dust limit',
  other_asset: 'in an asset the trace did not follow',
  not_traced: 'none of the traced money was assigned to it',
}

function ContextCard({ edge }: { edge: FlowEdge }) {
  const others = edge.others ?? []
  return (
    <>
      <span className="block font-medium">
        {plural(others.length, 'other transfer')} · context, not the suspect wallet&rsquo;s money
      </span>
      {others.slice(0, LISTED).map((t) => (
        <span key={t.id} className="mt-1.5 block">
          <span className="tabular block font-mono text-muted">
            {formatAmount(t.amount, t.asset)} · {formatDateTime(t.block_time)} · {WHY[t.why]}
          </span>
          <span className="block break-all font-mono">{t.tx_hash}</span>
        </span>
      ))}
      {others.length > LISTED && <span className="mt-1.5 block text-muted">and {count(others.length - LISTED)} more</span>}
    </>
  )
}

function EdgeCard({ edge, flows }: { edge: FlowEdge; flows: ReadonlyMap<string, FlowRisk> }) {
  if (edge.context) return <ContextCard edge={edge} />
  const many = edge.transfers.length > 1
  const risk = edgeRisk(edge.transfers.map((t) => t.id), flows)
  const reasons = [...new Set(edge.transfers.flatMap((t) => flows.get(t.id)?.reasons ?? []))]
  return (
    <>
      <span className="tabular block font-mono font-medium">
        {many && <span className="font-sans">{edge.transfers.length} transfers · </span>}
        {formatAmount(edge.amount, edge.asset)}
      </span>
      {risk && (
        <span className="mt-1 block">
          <span className="font-semibold">{RISK_WORDS[risk]} risk:</span> {reasons.join('; ')}
        </span>
      )}
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
