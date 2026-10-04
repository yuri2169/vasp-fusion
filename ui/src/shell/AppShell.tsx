import { FxProvider } from '../components/Rupees'
import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router'
import { ApiError, onUnauthorized } from '../api/client'
import { keys, useMe } from '../api/queries'
import { ErrorState } from '../components/ErrorState'
import { cx } from '../lib/cx'
import { SignInPage } from '../pages/SignInPage'
import { Footer } from './Footer'
import { Header } from './Header'
import { PageBoundary } from './PageBoundary'

/** The frame every screen sits in: the header (wordmark, places, search, officer, theme),
 *  the content, and the status bar with the colour key. The page scrolls, not a pane in it;
 *  in this flex column children stretch with `flex-1 min-h-0`, never `h-full`. It starts at
 *  GET /api/auth/me: a server that requires a login shows the sign-in screen first. */
export function AppShell() {
  const me = useMe()
  const client = useQueryClient()
  const { pathname } = useLocation()

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
  if (!me.data) return <div className="min-h-full bg-paper" aria-busy="true" />
  if (me.data.auth_required && !me.data.officer) return <SignInPage />

  // The landing is full-bleed (its own veil and grid); every other screen sits in the content column.
  const home = pathname === '/'
  return (
    <FxProvider>
    <div className="flex min-h-full flex-col bg-paper text-ink print:block print:min-h-0 print:bg-transparent">
      <a href="#content" className="sr-only z-50 bg-surface px-3 py-2 text-base font-medium text-ink focus:not-sr-only focus:fixed focus:left-3 focus:top-3">
        Skip to content
      </a>
      <Header />
      <main
        id="content"
        tabIndex={-1}
        className={cx('flex min-h-0 w-full flex-1 flex-col outline-none print:max-w-none print:p-0', !home && 'mx-auto max-w-content px-3 py-4 sm:px-6')}
      >
        <PageBoundary resetKey={pathname}>
          <Outlet />
        </PageBoundary>
      </main>
      <Footer />
    </div>
    </FxProvider>
  )
}
