import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { PageBoundary } from './PageBoundary'

let broken = true
function Page() {
  if (broken) throw new Error('boom')
  return <p>The page</p>
}

describe('PageBoundary', () => {
  beforeEach(() => {
    broken = true
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('says what to do when a page fails to draw, and draws it again on "Try again"', async () => {
    render(
      <PageBoundary resetKey="/cases/a">
        <Page />
      </PageBoundary>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('This page could not be shown')
    expect(screen.getByRole('alert')).toHaveTextContent('Nothing was changed or lost')
    broken = false
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.getByText('The page')).toBeInTheDocument()
  })

  it('clears itself when the officer goes to another page', () => {
    const { rerender } = render(
      <PageBoundary resetKey="/cases/a">
        <Page />
      </PageBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()
    broken = false
    rerender(
      <PageBoundary resetKey="/cases/b">
        <Page />
      </PageBoundary>,
    )
    expect(screen.getByText('The page')).toBeInTheDocument()
  })
})
