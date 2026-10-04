import { lazy, Suspense, type ReactNode } from 'react'
import { Route, Routes } from 'react-router'
import { Skeleton } from './components/Skeleton'
import { CasePage } from './pages/CasePage'
import { CasesPage } from './pages/CasesPage'
import { NewCasePage } from './pages/NewCasePage'
import { NotFoundPage } from './pages/PlaceholderPage'
import { StartPage } from './pages/StartPage'
import { AppShell } from './shell/AppShell'

// The request desk is loaded when it is first opened, so the first paint of a case does not carry it.
const DeskPage = lazy(() => import('./pages/DeskPage').then((m) => ({ default: m.DeskPage })))
const VaspPage = lazy(() => import('./pages/VaspPage').then((m) => ({ default: m.VaspPage })))
const RequestsPage = lazy(() => import('./pages/RequestsPage').then((m) => ({ default: m.RequestsPage })))
const RequestPage = lazy(() => import('./pages/RequestPage').then((m) => ({ default: m.RequestPage })))

// So are the pages an officer goes to between cases: the dashboard, a wallet, the labels, the model, the watchlist.
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const WalletPage = lazy(() => import('./pages/WalletPage').then((m) => ({ default: m.WalletPage })))
const LabelsPage = lazy(() => import('./pages/LabelsPage').then((m) => ({ default: m.LabelsPage })))
const ModelPage = lazy(() => import('./pages/ModelPage').then((m) => ({ default: m.ModelPage })))
const WatchlistPage = lazy(() => import('./pages/WatchlistPage').then((m) => ({ default: m.WatchlistPage })))

// The component kit shows every component on the demo fixtures, so it exists only where the
// fixtures do (`npm run dev`, a VITE_API=mock build). A live build has no /kit and none of its code.
const KitPage =
  import.meta.env.VITE_API === 'live' ? null : lazy(() => import('./pages/KitPage').then((m) => ({ default: m.KitPage })))

const later = (page: ReactNode) => (
  <Suspense
    fallback={
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton width="30%" />
        <Skeleton width="60%" />
      </div>
    }
  >
    {page}
  </Suspense>
)

/** Every route sits inside the shell (header, status bar). `/` is the landing. The providers are in main.tsx. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<StartPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/new" element={<NewCasePage />} />
        <Route path="cases/:id" element={<CasePage />} />
        <Route path="desk" element={later(<DeskPage />)} />
        <Route path="vasps/:name" element={later(<VaspPage />)} />
        <Route path="requests" element={later(<RequestsPage />)} />
        <Route path="requests/:id" element={later(<RequestPage />)} />
        <Route path="dashboard" element={later(<DashboardPage />)} />
        <Route path="wallets/:chain/:address" element={later(<WalletPage />)} />
        <Route path="labels" element={later(<LabelsPage />)} />
        <Route path="model" element={later(<ModelPage />)} />
        <Route path="watchlist" element={later(<WatchlistPage />)} />
        {KitPage && <Route path="kit" element={later(<KitPage />)} />}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
