import type { ReactNode, SVGAttributes } from 'react'
import { Tip, useTip } from '../components/Tip'
import { linear, niceTicks } from './scale'

/** The drawing area of an x/y plot, in SVG units (one unit is one CSS pixel at full width). */
const W = 520
const PAD = { left: 52, right: 18, top: 14, bottom: 46 }

export interface Frame {
  x: (v: number) => number
  y: (v: number) => number
  left: number
  right: number
  top: number
  bottom: number
}

const TEXT = { fontSize: 12, fill: 'var(--fg-muted)' } as const

/** Axes, a recessive grid and tick labels; the marks are drawn by `children`. One x axis, one y axis. */
export function PlotFrame({
  label,
  height = 320,
  xDomain,
  yDomain,
  xTicks,
  yTicks,
  xTitle,
  yTitle,
  xFormat = String,
  yFormat = String,
  children,
}: {
  /** The chart in one sentence, for a screen reader. */
  label: string
  height?: number
  xDomain: [number, number]
  yDomain: [number, number]
  xTicks?: number[]
  yTicks?: number[]
  xTitle: string
  yTitle: string
  xFormat?: (v: number) => string
  yFormat?: (v: number) => string
  children: (frame: Frame) => ReactNode
}) {
  const frame: Frame = {
    left: PAD.left,
    right: W - PAD.right,
    top: PAD.top,
    bottom: height - PAD.bottom,
    x: linear(xDomain[0], xDomain[1], PAD.left, W - PAD.right),
    y: linear(yDomain[0], yDomain[1], height - PAD.bottom, PAD.top),
  }
  const xs = (xTicks ?? niceTicks(xDomain[0], xDomain[1])).filter((t) => t >= xDomain[0] && t <= xDomain[1])
  const ys = (yTicks ?? niceTicks(yDomain[0], yDomain[1])).filter((t) => t >= yDomain[0] && t <= yDomain[1])
  return (
    <svg viewBox={`0 0 ${W} ${height}`} role="group" aria-label={label} className="tabular block w-full" style={{ maxWidth: W }}>
      {ys.map((t) => (
        <g key={`y${t}`}>
          <line x1={frame.left} x2={frame.right} y1={frame.y(t)} y2={frame.y(t)} stroke="var(--rule)" strokeWidth={1} />
          <text x={frame.left - 8} y={frame.y(t)} dy="0.32em" textAnchor="end" {...TEXT}>
            {yFormat(t)}
          </text>
        </g>
      ))}
      {xs.map((t) => (
        <g key={`x${t}`}>
          <line x1={frame.x(t)} x2={frame.x(t)} y1={frame.bottom} y2={frame.bottom + 4} stroke="var(--rule-strong)" strokeWidth={1} />
          <text x={frame.x(t)} y={frame.bottom + 18} textAnchor="middle" {...TEXT}>
            {xFormat(t)}
          </text>
        </g>
      ))}
      <line x1={frame.left} x2={frame.right} y1={frame.bottom} y2={frame.bottom} stroke="var(--rule-strong)" strokeWidth={1} />
      <text x={(frame.left + frame.right) / 2} y={height - 6} textAnchor="middle" {...TEXT}>
        {xTitle}
      </text>
      <text transform={`translate(13 ${(frame.top + frame.bottom) / 2}) rotate(-90)`} textAnchor="middle" {...TEXT}>
        {yTitle}
      </text>
      {children(frame)}
    </svg>
  )
}

/** One point: an 8px dot with a ring in the surface colour, a hit area larger than the dot, and a
 *  card on hover and on keyboard focus. */
export function PlotPoint({ cx, cy, name, children }: { cx: number; cy: number; name: string; children: ReactNode }) {
  const tip = useTip()
  return (
    <g tabIndex={0} role="img" aria-label={name} {...(tip.bind as unknown as SVGAttributes<SVGGElement>)} style={{ outline: 'none' }} className="plot-point">
      <circle cx={cx} cy={cy} r={14} fill="transparent" />
      <circle cx={cx} cy={cy} r={tip.open ? 6 : 4.5} fill="var(--fg)" stroke="var(--surface)" strokeWidth={2} />
      <Tip id={tip.id} anchor={tip.anchor}>
        {children}
      </Tip>
    </g>
  )
}

export function PlotLine({ points }: { points: [number, number][] }) {
  if (points.length < 2) return null
  return <polyline points={points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')} fill="none" stroke="var(--fg)" strokeWidth={2} strokeLinejoin="round" />
}

/** A dashed line to read the marks against (the diagonal of a reliability plot, a baseline), named where it ends. */
export function PlotReference({
  from,
  to,
  name,
  at = 1,
  anchor = 'end',
}: {
  from: [number, number]
  to: [number, number]
  name: string
  /** Where along the line its name is written, 0 (start) to 1 (end); the name sits just under the line. */
  at?: number
  anchor?: 'start' | 'end'
}) {
  const x = from[0] + (to[0] - from[0]) * at
  const y = from[1] + (to[1] - from[1]) * at
  return (
    <g>
      <line x1={from[0]} y1={from[1]} x2={to[0]} y2={to[1]} stroke="var(--rule-strong)" strokeWidth={1.5} strokeDasharray="5 4" />
      <text x={x - (anchor === 'end' ? 6 : -6)} y={y + 16} textAnchor={anchor} {...TEXT}>
        {name}
      </text>
    </g>
  )
}

/** The same figures as rows: every chart has one, folded under it. */
export function ChartTable({ caption, head, rows }: { caption: string; head: string[]; rows: string[][] }) {
  return (
    <details className="mt-2 text-sm">
      <summary className="cursor-pointer select-none text-muted underline decoration-rule-strong underline-offset-2 hover:text-fg">Show as table</summary>
      <div className="mt-2 max-h-64 overflow-auto rounded border border-rule">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {head.map((h) => (
                <th key={h} scope="col" className="eyebrow sticky top-0 bg-sunk px-2.5 py-1.5 text-right first:text-left">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-rule">
                {r.map((cell, j) => (
                  <td key={j} className="tabular px-2.5 py-1 text-right font-mono first:text-left">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  )
}
