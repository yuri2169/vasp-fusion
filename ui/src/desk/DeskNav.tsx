import { NavLink } from 'react-router'
import { cx } from '../lib/cx'

const VIEWS = [
  { to: '/desk', name: 'By exchange' },
  { to: '/requests', name: 'All requests' },
]

/** The desk's two views of the same work: what is owed to each exchange, and every request ever drafted. */
export function DeskNav({ counts }: { counts?: { exchanges?: number; requests?: number } }) {
  const count = [counts?.exchanges, counts?.requests]
  return (
    <nav aria-label="Request desk views" className="mb-6 flex gap-1 border-b border-rule-strong">
      {VIEWS.map(({ to, name }, i) => (
        <NavLink
          key={to}
          to={to}
          end
          className={({ isActive }) =>
            cx(
              '-mb-px inline-flex h-9 items-center gap-1.5 rounded-t border border-b-0 px-3.5 text-base',
              isActive ? 'border-rule-strong bg-surface font-semibold text-fg' : 'border-transparent text-muted hover:bg-sunk hover:text-fg',
            )
          }
        >
          {name}
          {count[i] != null && <span className="tabular font-mono text-sm text-muted">{count[i]}</span>}
        </NavLink>
      ))}
    </nav>
  )
}
