import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { buttonClass } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'

/** A place in the nav whose screen a later UI phase builds (U3: desk; U4: dashboard, labels, model).
 *  It says what will be here, and sends the officer somewhere that works today. */
export function PlaceholderPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState
        title="This screen is not built yet"
        action={
          <Link to="/cases" className={buttonClass('secondary')}>
            Go to cases
          </Link>
        }
      >
        {children}
      </EmptyState>
    </>
  )
}

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="There is no page here" />
      <EmptyState
        title="The address may be mistyped, or the page has moved"
        action={
          <Link to="/cases" className={buttonClass('secondary')}>
            Go to cases
          </Link>
        }
      >
        To open a case, paste its wallet address in the search bar.
      </EmptyState>
    </>
  )
}
