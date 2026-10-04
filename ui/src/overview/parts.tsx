import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Frame } from '../components/Panel'
import { cx } from '../lib/cx'

/** A part of a page on its own sheet: a printed heading, an optional way to the list behind it, the content. */
export function Panel({
  title,
  more,
  note,
  children,
  className,
}: {
  title: string
  more?: { to: string; text: string }
  /** One quiet line under the heading: what is counted, and what is not. */
  note?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section aria-label={title} className={cx('flex flex-col gap-3 panel p-4', className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="eyebrow">{title}</h2>
        {more && (
          <Link to={more.to} className="text-sm text-muted underline decoration-rule-strong underline-offset-2 hover:text-fg">
            {more.text}
          </Link>
        )}
      </div>
      {note && <p className="-mt-1.5 max-w-prose text-sm text-muted">{note}</p>}
      <Frame>{children}</Frame>
    </section>
  )
}

export interface LedgerEntry {
  key: string
  name: string
  /** The figure as written; "not measured" where there is none. */
  value: string
  /** What exactly is counted. */
  note?: string
  to?: string
  /** Something to act on: the figure is set in red. */
  alert?: boolean
}

/** The page's counts on one ruled line, as the totals row of a register: a figure, what it counts,
 *  and (when it has a list behind it) a link to that list. Not cards: one sheet, hairlines between. */
export function Ledger({ entries, label, perRow = 'all' }: { entries: LedgerEntry[]; label: string; perRow?: 'all' | 3 }) {
  return (
    // A list, not a <dl>: a count that opens its list is one link, and a <dl> may not hold a link
    // around its term and value.
    <ul
      aria-label={label}
      className={cx(
        'grid grid-cols-2 overflow-hidden panel sm:grid-cols-3',
        perRow === 'all' && 'lg:auto-cols-fr lg:grid-flow-col lg:grid-cols-none',
      )}
    >
      {entries.map((e) => {
        const body = (
          <>
            <span className="colhead">{e.name}</span>
            <span className={cx('figure mt-1 whitespace-nowrap', e.alert ? 'text-danger' : 'text-ink')} style={{ fontSize: 28 }}>
              {e.value}
            </span>
            {e.note && <span className="mt-1 text-2xs text-ink-dim">{e.note}</span>}
          </>
        )
        const cell = 'flex h-full flex-col px-4 py-3'
        return (
          <li key={e.key} className="-mb-px -mr-px border-b border-r border-rule-soft">
            {e.to ? (
              <Link to={e.to} className={cx(cell, 'row-hover')}>
                {body}
              </Link>
            ) : (
              <div className={cell}>{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}
