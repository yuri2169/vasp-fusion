import { Link } from 'react-router'
import { cx } from '../lib/cx'
import { formatPercent } from '../lib/format'
import { Tip, useTip } from '../components/Tip'

/** The fills are statuses, as on the funds bar: saffron = an exchange was named, seal = sanctioned
 *  or mixer, ink = another settled state, and one hatch for what is unresolved. */
export type ShareFill = 'named' | 'party' | 'seal' | 'open'

const FILL: Record<ShareFill, string> = {
  named: 'bg-saffron',
  party: 'bg-fg',
  seal: 'bg-seal',
  open: 'hatch border border-rule-strong bg-sunk',
}

export interface SharePart {
  key: string
  name: string
  value: number
  fill: ShareFill
  to?: string
}

function Segment({ part, total, unit }: { part: SharePart; total: number; unit: (n: number) => string }) {
  const tip = useTip()
  return (
    <span
      data-testid="share-segment"
      onMouseEnter={tip.bind.onMouseEnter}
      onMouseLeave={tip.bind.onMouseLeave}
      style={{ flexBasis: `${((part.value / total) * 100).toFixed(1)}%` }}
      className={cx('h-full min-w-[4px] shrink grow-0 rounded-sm', FILL[part.fill])}
    >
      <Tip id={tip.id} anchor={tip.anchor}>
        <span className="block font-medium">{part.name}</span>
        <span className="tabular mt-0.5 block font-mono text-muted">
          {unit(part.value)} · {formatPercent(part.value / total)}
        </span>
      </Tip>
    </span>
  )
}

/** One stacked bar of a whole, every part named under it with its count. A part with `to` is a
 *  link to the list behind it; a part of zero is listed but has no segment. */
export function ShareBar({ parts, caption, unit }: { parts: SharePart[]; caption: string; unit: (n: number) => string }) {
  const total = parts.reduce((sum, p) => sum + p.value, 0)
  const summary = parts.map((p) => `${unit(p.value)} ${p.name}`).join(', ')
  return (
    <div className="flex flex-col gap-3">
      {total > 0 && (
        <div role="img" aria-label={`${caption}: ${summary}`} className="flex h-3 w-full gap-0.5">
          {parts
            .filter((p) => p.value > 0)
            .map((p) => (
              <Segment key={p.key} part={p} total={total} unit={unit} />
            ))}
        </div>
      )}
      <ul aria-label={caption} className="flex flex-col">
        {parts.map((p) => {
          const body = (
            <>
              <span aria-hidden className={cx('h-2.5 w-2.5 shrink-0 rounded-sm', FILL[p.fill])} />
              <span className="min-w-0 flex-1 truncate text-sm text-fg">{p.name}</span>
              <span className="tabular font-mono text-sm text-fg">{p.value.toLocaleString('en-US')}</span>
              <span className="tabular w-16 text-right font-mono text-xs text-muted">{total > 0 ? formatPercent(p.value / total) : ''}</span>
            </>
          )
          const row = 'flex items-center gap-2.5 rounded-sm px-1.5 py-1.5'
          return (
            <li key={p.key}>
              {p.to ? (
                <Link to={p.to} className={cx(row, 'hover:bg-sunk')}>
                  {body}
                </Link>
              ) : (
                <div className={row}>{body}</div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
