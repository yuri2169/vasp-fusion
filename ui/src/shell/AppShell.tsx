import { useQueryClient } from '@tanstack/react-query'
import { FlaskConical } from 'lucide-react'
import { useEffect } from 'react'
import { Outlet } from 'react-router'
import { ApiError, onUnauthorized } from '../api/client'
import { keys, useDataSource, useMe } from '../api/queries'
import { ErrorState } from '../components/ErrorState'
import { SignInPage } from '../pages/SignInPage'
import { GlobalSearch } from './GlobalSearch'
import { NavRail } from './NavRail'

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
      className="inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border border-dashed border-rule-strong px-2 text-xs font-medium text-muted"
    >
      <FlaskConical size={13} aria-hidden />
      {source === 'mock' ? 'Demo data' : 'Includes demo data'}
    </span>
  )
}

/** The frame every screen sits in: ink rail, search bar, content. It starts at
 *  GET /api/auth/me: a server that requires a login shows the sign-in screen first. */
export function AppShell() {
  const me = useMe()
  const client = useQueryClient()

  // Any route answering 401 "Sign in to continue." means the session ended: ask who is signed in again.
  useEffect(() => onUnauthorized(() => void client.invalidateQueries({ queryKey: keys.me })), [client])

  if (me.isError)
    return (
      <div className="mx-auto flex min-h-screen max-w-xl flex-col justify-center px-6">
        <ErrorState
          title="VASP-FUSION could not start"
          detail={me.error instanceof ApiError ? me.error.detail : 'The server did not answer. Check that it is running, then try again.'}
          onRetry={() => void me.refetch()}
        />
      </div>
    )
  if (!me.data) return <div className="min-h-screen bg-page" aria-busy="true" />
  if (me.data.auth_required && !me.data.officer) return <SignInPage />

  return (
    <div className="flex min-h-screen bg-page text-fg">
      <a
        href="#content"
        className="sr-only z-50 rounded bg-surface px-3 py-2 text-sm font-medium text-fg focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>
      <NavRail />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-15 shrink-0 items-center gap-4 border-b border-rule bg-page px-5 lg:px-8">
          <GlobalSearch />
          <DataSourceTag />
        </header>
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-content flex-1 px-5 py-7 outline-none lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
