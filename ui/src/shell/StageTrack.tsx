import { useEffect, useRef } from 'react'
import { layerColor, type Layer } from '../components/Panel'

/** The nine stages as a serpentine track (BTC-FUSION's StageTrack, ported).
 *
 *  A boustrophedon path (left to right, turn, right to left, turn, left to right) uses the
 *  width it has and reads as one continuous run of work. Progress is a second copy of the
 *  same path revealed by a dash offset, so the fill follows the curve through both turns.
 *  It is a picture: the stages are named in words beside it, so it is hidden from a screen
 *  reader and holds no tab stop. */
const VB_W = 1000
const VB_H = 316
const X0 = 56
const X1 = 792
const X2 = 208
const X3 = 944
const Y = [58, 154, 250]
const R = (Y[1] - Y[0]) / 2

const D = `M ${X0} ${Y[0]} H ${X1} A ${R} ${R} 0 0 1 ${X1} ${Y[1]} H ${X2} A ${R} ${R} 0 0 0 ${X2} ${Y[2]} H ${X3}`

const L1 = X1 - X0
const ARC = Math.PI * R
const L2 = X1 - X2
const L3 = X3 - X2
const TOTAL = L1 + ARC + L2 + ARC + L3

/** Three nodes per straight run, inset from the ends so that none sits on a turn. */
const T = [
  [0.16, 0.5, 0.84],
  [0.16, 0.5, 0.84],
  [0.14, 0.47, 0.8],
]
const AT: number[] = [...T[0].map((t) => t * L1), ...T[1].map((t) => L1 + ARC + t * L2), ...T[2].map((t) => L1 + ARC + L2 + ARC + t * L3)]
// Nodes sit on the straight runs only, so their centres are known without measuring the path.
const PTS: { x: number; y: number }[] = [
  ...T[0].map((t) => ({ x: X0 + t * L1, y: Y[0] })),
  ...T[1].map((t) => ({ x: X1 - t * L2, y: Y[1] })),
  ...T[2].map((t) => ({ x: X2 + t * L3, y: Y[2] })),
]

const N_PACKETS = 5

export function StageTrack({
  stages,
  idx,
  layer = 'chain',
  live = false,
  notes = {},
  onPick,
}: {
  stages: [string, string][]
  /** The stage being run (a trace) or looked at (the landing's tour). */
  idx: number
  /** The colour of the run so far. A trace is on-chain work; the tour passes the stage's own layer. */
  layer?: Layer
  /** Packets travel the run so far: the work is still moving. Off under reduced motion. */
  live?: boolean
  /** A line under a stage's name (what a trace has read there). */
  notes?: Record<string, string>
  /** Pointer only; the same choice is offered as buttons beside the track. */
  onPick?: (i: number) => void
}) {
  const pathRef = useRef<SVGPathElement>(null)
  const packetRefs = useRef<(SVGCircleElement | null)[]>([])
  const colour = layerColor(layer)

  const filled = Math.min(AT[idx] ?? TOTAL, TOTAL)
  const filledRef = useRef(filled)
  useEffect(() => {
    filledRef.current = filled
  }, [filled])

  // Positions are written straight to the DOM: sixty re-renders a second of this SVG would be
  // visible work for no visible benefit. Time-based, so it runs alike at 60 and 120 Hz.
  useEffect(() => {
    const path = pathRef.current
    if (!live || !path || typeof path.getPointAtLength !== 'function') return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const offs = Array.from({ length: N_PACKETS }, (_, i) => i / N_PACKETS)
    let raf = 0
    let last = 0
    const tick = (t: number) => {
      const dt = Math.min(48, last ? t - last : 16)
      last = t
      const lim = Math.max(1, filledRef.current)
      offs.forEach((o, i) => {
        offs[i] = (o + dt * 0.00042) % 1
        const el = packetRefs.current[i]
        if (!el) return
        const q = path.getPointAtLength(offs[i] * lim)
        el.setAttribute('cx', String(q.x))
        el.setAttribute('cy', String(q.y))
        el.setAttribute('opacity', String(Math.max(0, Math.min(offs[i] / 0.08, (1 - offs[i]) / 0.12, 1)) * 0.9))
      })
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [live])

  return (
    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="h-auto w-full" aria-hidden="true" focusable="false">
      <path ref={pathRef} d={D} fill="none" stroke="var(--rule-soft)" strokeWidth={14} strokeLinecap="butt" />
      <path
        d={D}
        fill="none"
        stroke={colour}
        strokeWidth={14}
        strokeLinecap="butt"
        style={{ strokeDasharray: TOTAL, strokeDashoffset: TOTAL - filled, transition: 'stroke-dashoffset 900ms cubic-bezier(.16,1,.3,1), stroke 300ms' }}
      />
      {/* Drawn, not a marker: an SVG marker scales with the stroke width. */}
      <path d={`M ${X3 + 9} ${Y[2] - 15} L ${X3 + 37} ${Y[2]} L ${X3 + 9} ${Y[2] + 15} Z`} fill="var(--rule-soft)" />

      {live &&
        Array.from({ length: N_PACKETS }, (_, i) => (
          <circle
            key={i}
            r={4}
            ref={(el) => {
              packetRefs.current[i] = el
            }}
            fill="var(--surface)"
            opacity={0}
          />
        ))}

      {PTS.map((p, i) => {
        const done = i < idx
        const now = i === idx
        const name = stages[i]?.[0] ?? ''
        const note = notes[name]
        return (
          <g key={name} onClick={onPick && (() => onPick(i))} style={onPick ? { cursor: 'pointer' } : undefined}>
            {onPick && <rect x={p.x - 70} y={p.y - 28} width={140} height={92} fill="transparent" />}
            {now && live && (
              <rect x={p.x - 24} y={p.y - 24} width={48} height={48} fill={colour} opacity={0.18}>
                <animate attributeName="opacity" values=".24;.04;.24" dur="1.8s" repeatCount="indefinite" />
              </rect>
            )}
            {/* Square nodes: nothing in this language is a rounded token. */}
            <rect
              x={p.x - 18}
              y={p.y - 18}
              width={36}
              height={36}
              fill={done || now ? colour : 'var(--surface)'}
              stroke={done || now ? colour : 'var(--rule)'}
              strokeWidth={2}
              style={{ transition: 'fill 400ms, stroke 400ms' }}
            />
            {done ? (
              <path d={`M ${p.x - 6} ${p.y} l 4.4 4.6 L ${p.x + 7} ${p.y - 5.4}`} fill="none" stroke="var(--surface)" strokeWidth={3} strokeLinecap="square" />
            ) : (
              <text x={p.x} y={p.y + 5} textAnchor="middle" fontSize={15} fontWeight={700} fill={now ? 'var(--surface)' : 'var(--ink-dim)'} style={{ fontFamily: 'Archivo, sans-serif' }}>
                {i + 1}
              </text>
            )}
            <text
              x={p.x}
              y={p.y + 40}
              textAnchor="middle"
              fontSize={15}
              fontWeight={done || now ? 700 : 600}
              fill={done || now ? 'var(--ink)' : 'var(--ink-dim)'}
              style={{ fontFamily: 'Archivo, sans-serif', textTransform: 'uppercase', letterSpacing: '.01em', transition: 'fill 400ms' }}
            >
              {name}
            </text>
            {note && (
              <text x={p.x} y={p.y + 57} textAnchor="middle" fontSize={12} fill={now ? colour : 'var(--ink-soft)'} style={{ fontFamily: '"Spline Sans Mono", monospace' }}>
                {note}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
