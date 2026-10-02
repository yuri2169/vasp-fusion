import { Component, FolderOpen, Gauge, LayoutDashboard, LogOut, Send, Tags, type LucideIcon } from 'lucide-react'
import { NavLink } from 'react-router'
import { ApiError } from '../api/client'
import { useMe, useSignOut } from '../api/queries'
import { useToast } from '../components/Toast'
import { cx } from '../lib/cx'
import { ThemeToggle } from '../theme/ThemeToggle'

const PLACES: { to: string; name: string; Icon: LucideIcon }[] = [
  { to: '/cases', name: 'Cases', Icon: FolderOpen },
  { to: '/desk', name: 'Request desk', Icon: Send },
  { to: '/dashboard', name: 'Dashboard', Icon: LayoutDashboard },
  { to: '/labels', name: 'Labels', Icon: Tags },
  { to: '/model', name: 'Model', Icon: Gauge },
]

/** Rows in the rail: icon only under 1024px (the name stays for screen readers and as a tooltip). */
const row = 'flex h-9 w-full items-center gap-3 rounded px-2.5 text-sm max-lg:justify-center max-lg:px-0'
const label = 'truncate max-lg:sr-only'

function Wordmark() {
  return (
    <div className="flex h-15 items-center gap-2.5 px-4 max-lg:justify-center max-lg:px-0">
      {/* The mark: a wallet, a hop, and the stamp it ends in. */}
      <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden className="shrink-0">
        <rect width="32" height="32" rx="4" fill="var(--rail-active)" />
        <circle cx="7.5" cy="16" r="2.5" fill="var(--rail-fg)" />
        <path d="M10 16h6" stroke="var(--rail-fg)" strokeWidth="1.5" />
        <rect x="16.5" y="10.5" width="10" height="11" rx="1" fill="var(--saffron)" />
      </svg>
      <span className="display text-base tracking-wide text-rail-fg max-lg:sr-only">VASP-FUSION</span>
    </div>
  )
}

function initials(name: string): string {
  const words = name.replace(/\b(Insp|Inspector|SI|ASI|DSP|ACP|DCP|Dr|Mr|Ms|Mrs|Shri|Smt)\.?\s/gi, '').split(/\s+/).filter(Boolean)
  return (words.length > 1 ? words[0][0] + words.at(-1)![0] : (words[0] ?? '?').slice(0, 2)).toUpperCase()
}

/** Who is using the tool. Light on purpose: a name, a post, a way out. */
function OfficerBlock() {
  const me = useMe()
  const signOut = useSignOut()
  const toast = useToast()
  const officer = me.data?.officer

  if (!me.data) return <div className="h-12" />
  if (!officer)
    return <p className="px-2.5 text-xs text-rail-muted max-lg:sr-only">{me.data.auth_required ? 'Not signed in' : 'No sign-in on this server'}</p>

  return (
    <div className="flex items-center gap-2.5 px-1 max-lg:flex-col max-lg:px-0">
      <span
        aria-hidden
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-sm border border-rail-muted font-mono text-xs font-medium text-rail-fg"
      >
        {initials(officer.name)}
      </span>
      <div className="min-w-0 flex-1 max-lg:sr-only">
        <p className="truncate text-sm font-medium text-rail-fg">{officer.name}</p>
        {officer.post && <p className="truncate text-xs text-rail-muted">{officer.post}</p>}
      </div>
      {me.data.auth_required && (
        <button
          type="button"
          aria-label="Sign out"
          title="Sign out"
          onClick={() =>
            signOut.mutate(undefined, {
              onError: (e) => toast.show({ kind: 'error', title: 'Not signed out', detail: e instanceof ApiError ? e.detail : undefined }),
            })
          }
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded text-rail-muted hover:bg-rail-active hover:text-rail-fg"
        >
          <LogOut size={15} aria-hidden />
        </button>
      )}
    </div>
  )
}

/** The ink rail on the left: the five places an investigator goes, and who they are. */
export function NavRail() {
  return (
    <aside className="on-rail sticky top-0 flex h-screen w-16 shrink-0 flex-col bg-rail text-rail-fg lg:w-rail">
      <Wordmark />
      <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5 px-2.5 pt-3">
        {PLACES.map(({ to, name, Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={name}
            className={({ isActive }) =>
              cx(
                row,
                'relative',
                isActive
                  ? 'bg-rail-active font-semibold text-rail-fg before:absolute before:inset-y-1.5 before:-left-2.5 before:w-[3px] before:rounded-r-sm before:bg-rail-fg'
                  : 'text-rail-muted hover:bg-rail-active hover:text-rail-fg',
              )
            }
          >
            <Icon size={17} aria-hidden className="shrink-0" />
            <span className={label}>{name}</span>
          </NavLink>
        ))}
      </nav>
      <div className="flex flex-col gap-0.5 px-2.5 pb-2">
        <NavLink
          to="/kit"
          title="Component kit"
          className={({ isActive }) => cx(row, isActive ? 'bg-rail-active text-rail-fg' : 'text-rail-muted hover:bg-rail-active hover:text-rail-fg')}
        >
          <Component size={16} aria-hidden className="shrink-0" />
          <span className={label}>Component kit</span>
        </NavLink>
        <ThemeToggle className={cx(row, 'text-rail-muted hover:bg-rail-active hover:text-rail-fg [&>span]:max-lg:sr-only')} />
      </div>
      <div className="border-t border-rail-rule px-2.5 py-3">
        <OfficerBlock />
      </div>
    </aside>
  )
}
