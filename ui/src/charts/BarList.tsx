import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { cx } from '../lib/cx'
import { barPercent } from './scale'

export interface BarRow {
  key: string
  /** What the bar stands for: a name, a chain badge, a tier tag. */
  label: ReactNode
  value: number
  /** The value as it is written (mono, at the end of the row). */
  valueText: string
  /** A second, quieter figure beside it ("2 cases"). */
  note?: string
  /** The list behind the bar. */
  to?: string
  /** For screen readers and the row's title: the whole row in words. */
  title?: string
}

/** Ranked horizontal bars of one measure: one hue, a thin mark, the value written at the end of
 *  every row (so the chart is its own table). A row with `to` is a link to the list behind it. */
export function BarList({
  rows,
  caption,
  labelWidth = '9rem',
  max,
  empty,
  className,
}: {
  rows: BarRow[]
  /** Read out as the list's name. */
  caption: string
  labelWidth?: string
  /** The value a full-width bar stands for; the largest row by default. */
  max?: number
  empty?: ReactNode
  className?: string
}) {
  if (rows.length === 0) return <p className="text-base text-muted">{empty ?? 'Nothing to count yet.'}</p>
  const top = max ?? Math.max(...rows.map((r) => r.value))
  return (
    <ul aria-label={caption} className={cx('flex flex-col', className)}>
      {rows.map((r) => {
        const body = (
          <>
            <span className="min-w-0 truncate text-base text-fg" style={{ width: labelWidth, flex: `0 0 ${labelWidth}` }}>
              {r.label}
            </span>
            <span aria-hidden className="flex h-2 min-w-0 flex-1 items-center">
              <span data-testid="bar" className="block h-2 rounded-r bg-fg" style={{ width: `${barPercent(r.value, top)}%` }} />
            </span>
            <span className="tabular shrink-0 whitespace-nowrap text-right font-mono text-base text-fg">{r.valueText}</span>
            {r.note !== undefined && <span className="tabular w-20 shrink-0 whitespace-nowrap text-right text-sm text-muted">{r.note}</span>}
          </>
        )
        const row = 'flex items-center gap-3 rounded-sm px-1.5 py-1.5'
        return (
          <li key={r.key} title={r.title}>
            {r.to ? (
              <Link to={r.to} className={cx(row, 'hover:bg-sunk')}>
                {body}
              </Link>
            ) : (
              <div className={row}>{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
