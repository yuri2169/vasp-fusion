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
    <nav aria-label="Request desk views" className="mb-4 flex gap-0.5 border-b border-rule">
      {VIEWS.map(({ to, name }, i) => (
        <NavLink
          key={to}
          to={to}
          end
          className={({ isActive }) =>
            cx(
              '-mb-px inline-flex h-9 items-center gap-2 border-b-2 px-3 text-base transition-colors duration-150',
              isActive ? 'border-ink font-semibold text-ink' : 'border-transparent text-ink-dim hover:text-ink-soft',
            )
          }
        >
          {name}
          {count[i] != null && <span className="tabular font-mono text-2xs text-ink-dim">{count[i]}</span>}
        </NavLink>
      ))}
    </nav>
  )
}
