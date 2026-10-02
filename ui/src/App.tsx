import { Navigate, Route, Routes } from 'react-router'
import { CasePage } from './pages/CasePage'
import { CasesPage } from './pages/CasesPage'
import { KitPage } from './pages/KitPage'
import { NotFoundPage, PlaceholderPage } from './pages/PlaceholderPage'
import { AppShell } from './shell/AppShell'

/** Every route sits inside the shell (nav rail, search bar). The providers are in main.tsx. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/cases" replace />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:id" element={<CasePage />} />
        <Route
          path="desk"
          element={
            <PlaceholderPage title="Request desk">
              The desk groups traced wallets by exchange: one consolidated request per exchange, drafted, approved, sent and
              followed up.
            </PlaceholderPage>
          }
        />
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
