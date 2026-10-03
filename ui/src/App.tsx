import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { Skeleton } from './components/Skeleton'
import { CasePage } from './pages/CasePage'
import { CasesPage } from './pages/CasesPage'
import { KitPage } from './pages/KitPage'
import { NewCasePage } from './pages/NewCasePage'
import { NotFoundPage, PlaceholderPage } from './pages/PlaceholderPage'
import { AppShell } from './shell/AppShell'

// The request desk is loaded when it is first opened, so the first paint of a case does not carry it.
const DeskPage = lazy(() => import('./pages/DeskPage').then((m) => ({ default: m.DeskPage })))
const VaspPage = lazy(() => import('./pages/VaspPage').then((m) => ({ default: m.VaspPage })))
const RequestsPage = lazy(() => import('./pages/RequestsPage').then((m) => ({ default: m.RequestsPage })))
const RequestPage = lazy(() => import('./pages/RequestPage').then((m) => ({ default: m.RequestPage })))

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

/** Every route sits inside the shell (nav rail, search bar). The providers are in main.tsx. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/cases" replace />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/new" element={<NewCasePage />} />
        <Route path="cases/:id" element={<CasePage />} />
        <Route path="desk" element={later(<DeskPage />)} />
        <Route path="vasps/:name" element={later(<VaspPage />)} />
        <Route path="requests" element={later(<RequestsPage />)} />
        <Route path="requests/:id" element={later(<RequestPage />)} />
        <Route
          path="dashboard"
          element={
            <PlaceholderPage title="Dashboard">
              The dashboard counts open cases, requests awaiting a reply, and how much of each chain the label store covers.
            </PlaceholderPage>
          }
        />
        <Route
          path="labels"
          element={
            <PlaceholderPage title="Labels">
              The labels explorer searches every labelled address by owner, chain and tier, with the source of each label.
            </PlaceholderPage>
          }
        />
        <Route
          path="model"
          element={
            <PlaceholderPage title="Model">
              The model page shows how the deposit-address model was measured: its accuracy, its calibration, and what the
              numbers do not say.
            </PlaceholderPage>
          }
        />
        <Route path="kit" element={<KitPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
