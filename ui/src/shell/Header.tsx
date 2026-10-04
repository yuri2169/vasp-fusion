import { FlaskConical, LogOut } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { API_MODE } from '../api/api'
import { ApiError } from '../api/client'
import { useDataSource, useMe, useSignOut } from '../api/queries'
import { useToast } from '../components/Toast'
import { cx } from '../lib/cx'
import { ThemeToggle } from '../theme/ThemeToggle'
import { GlobalSearch } from './GlobalSearch'

/** `also`: other routes that belong to the same place (an exchange's page and a request are the desk's). */
const PLACES: { to: string; name: string; also?: string[] }[] = [
  { to: '/cases', name: 'Cases' },
  { to: '/desk', name: 'Request desk', also: ['/vasps', '/requests'] },
  { to: '/dashboard', name: 'Dashboard' },
  { to: '/watchlist', name: 'Watchlist' },
  { to: '/labels', name: 'Labels', also: ['/wallets'] },
  { to: '/model', name: 'Model' },
  // Named for what it is: a simulator, never "SAHYOG" alone.
  { to: '/sahyog-sim', name: 'SAHYOG simulator' },
  // The kit runs on the demo fixtures, so it is offered only where they are (App.tsx).
  ...(API_MODE !== 'live' ? [{ to: '/kit', name: 'Kit' }] : []),
]

/** Says so whenever what is on screen is not live data (the API's X-Data-Source header). */
function DataSourceTag() {
  const source = useDataSource()
  if (!source || source === 'live') return null
  return (
    <span
      title={
        source === 'mock'
          ? 'These are demonstration fixtures, not real cases. Nothing here is evidence.'
          : 'Some of what is listed here is demonstration fixtures, not real cases.'
      }
      className="inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap border border-dashed border-rule-strong px-2 text-2xs font-medium text-ink-soft"
    >
      <FlaskConical size={12} aria-hidden />
      <span className="max-md:sr-only">{source === 'mock' ? 'Demo data' : 'Includes demo data'}</span>
    </span>
  )
}

/** Who is using the tool: a name, a post, a way out. Every action is recorded under this name. */
function OfficerBlock() {
  const me = useMe()
  const signOut = useSignOut()
  const toast = useToast()
  const officer = me.data?.officer

  if (!me.data) return null
  if (!officer) return <p className="sr-only whitespace-nowrap text-2xs text-ink-dim lg:not-sr-only">{me.data.auth_required ? 'Not signed in' : 'Sign-in is switched off'}</p>

  return (
    <div className="flex shrink-0 items-center gap-2" title="Recorded with every case opened and every request sent">
      <div className="sr-only min-w-0 text-right leading-tight wide:not-sr-only">
        <p className="max-w-[160px] truncate text-sm font-medium text-ink">{officer.name}</p>
        {officer.post && <p className="max-w-[160px] truncate text-2xs text-ink-dim">{officer.post}</p>}
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
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center border border-rule text-ink-dim transition-colors duration-150 hover:bg-surface-3 hover:text-ink"
        >
          <LogOut size={14} aria-hidden />
        </button>
      )}
    </div>
  )
}

/** The header is the page, not a bar on it: transparent over the paper with one hairline.
 *  It takes a surface ground only once something has scrolled under it, because a
 *  transparent bar over moving text cannot be read. The wordmark is the way home. */
export function Header() {
  const { pathname } = useLocation()
  const home = pathname === '/'

  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header
      data-scrolled={scrolled || undefined}
      className={cx(
        'sticky top-0 z-30 flex h-12 shrink-0 items-center gap-2 border-b px-3 transition-colors duration-200 sm:gap-4 sm:px-6 print:hidden',
        scrolled ? 'border-rule bg-surface' : 'border-rule-soft bg-transparent',
      )}
    >
      <Link to="/" aria-label="VASP-Fusion: back to start" title="Back to start" className="group flex shrink-0 items-baseline gap-2">
        <span className="font-cond text-lg font-bold tracking-tight text-ink transition-colors duration-150 group-hover:text-chain">
          VASP<span className="text-chain">·</span>Fusion
        </span>
        <span className="hidden text-2xs text-ink-dim min-[1680px]:inline">wallet → exchange attribution</span>
      </Link>

      <nav aria-label="Main" className="flex min-w-0 items-center gap-0.5 overflow-x-auto [scrollbar-width:none] sm:ml-2 lg:shrink-0 [&::-webkit-scrollbar]:hidden">
        {PLACES.map(({ to, name, also }) => {
          const active = [to, ...(also ?? [])].some((p) => pathname === p || pathname.startsWith(`${p}/`))
          return (
            <Link
              key={to}
              to={to}
              aria-current={active ? 'page' : undefined}
              className={cx(
                'inline-flex h-12 items-center whitespace-nowrap border-b-2 px-2 text-base transition-colors duration-150 lg:px-3',
                active ? 'border-ink font-medium text-ink' : 'border-transparent text-ink-dim hover:text-ink-soft',
              )}
            >
              {name}
            </Link>
          )
        })}
      </nav>

      <div className="ml-auto flex min-w-[200px] flex-1 items-center justify-end gap-2 sm:gap-3 max-sm:min-w-0">
        {/* On the landing the paste box is the page's own; a second one here would be a way round it. */}
        {!home && <GlobalSearch />}
        <DataSourceTag />
        <OfficerBlock />
        <ThemeToggle />
      </div>
    </header>
  )
}
