import { QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { createQueryClient } from '../api/queries'
import { ToastProvider } from '../components/Toast'

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="location">{pathname + search}</output>
}

/** Render with everything a screen expects: router, query client, toasts.
 *  `screen.getByTestId('location')` reads the current route. */
export function renderApp(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const client = createQueryClient()
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <ToastProvider>
          {children}
          <Where />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  )
  return { user: userEvent.setup(), client, ...render(ui, { wrapper }) }
}
