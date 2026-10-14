import { screen, within } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../test/render'
import type { CaseDetail } from '../api/models'
import coindcxJson from '../test/fixtures/cases/tron-coindcx.json'
import { LeftOut, PresentPage, SCREENS } from './PresentPage'

const coindcx = coindcxJson as unknown as CaseDetail

function open(id: string, search = '') {
  return renderApp(
    <Routes>
      <Route path="cases/:id/present" element={<PresentPage />} />
      <Route path="cases/:id" element={<p>case page</p>} />
    </Routes>,
    { route: `/cases/${id}/present${search}` },
  )
}

const title = () => screen.getByRole('heading', { level: 1 })

describe('present mode', () => {
  it('opens on the finding: the exchange named, proximity and confidence apart', async () => {
    open('demo-tron-okx')
    expect(await screen.findByText('OKX', { selector: 'p' })).toBeInTheDocument()
    expect(title()).toHaveTextContent('1 · The finding')
    expect(screen.getByText(/A lead to confirm/)).toBeInTheDocument()
    expect(screen.getByText('Proximity')).toBeInTheDocument()
    expect(screen.getByText('Confidence')).toBeInTheDocument()
  })

  it('moves with the arrow keys and the number keys, and says where it is', async () => {
    const { user } = open('demo-tron-okx')
    await screen.findByText('OKX', { selector: 'p' })
    await user.keyboard('{ArrowRight}{ArrowRight}')
    expect(title()).toHaveTextContent('3 · What was left out, and why')
    expect(screen.getByTestId('location')).toHaveTextContent('/cases/demo-tron-okx/present?screen=3')
    expect(screen.getByText(/Screen 3 of 4/)).toBeInTheDocument()
    await user.keyboard('4')
    expect(title()).toHaveTextContent('4 · The handoff')
    await user.keyboard('{ArrowRight}')
    expect(title()).toHaveTextContent('4 · The handoff') // the last screen stays
    await user.keyboard('{ArrowLeft}')
    expect(title()).toHaveTextContent('3 ·')
    await user.keyboard('{Home}')
    expect(title()).toHaveTextContent('1 ·')
  })

  it('marks the screen it is on in the strip of four', async () => {
    open('demo-tron-okx', '?screen=2')
    await screen.findByRole('heading', { level: 1 })
    const strip = screen.getByRole('navigation', { name: 'Screens' })
    expect(within(strip).getAllByRole('button').map((b) => b.textContent)).toEqual([...SCREENS])
    expect(within(strip).getByRole('button', { name: 'The route' })).toHaveAttribute('aria-current', 'step')
  })

  it('leaves for the case page on Esc', async () => {
    const { user } = open('demo-tron-okx')
    await screen.findByText('OKX', { selector: 'p' })
    await user.keyboard('{Escape}')
    expect(screen.getByTestId('location')).toHaveTextContent(/^\/cases\/demo-tron-okx$/)
  })

  it('says why no exchange is named, and offers no request', async () => {
    const { user } = open('demo-eth-abstain')
    expect(await screen.findByText('No exchange is named')).toBeInTheDocument()
    expect(screen.getByText('What would change this')).toBeInTheDocument()
    await user.keyboard('4')
    expect(screen.getByText('No exchange request is offered')).toBeInTheDocument()
  })

  it('shows what was left out in the trace’s own counts', () => {
    renderApp(<LeftOut c={coindcx} />)
    const s = coindcx.trace_summary!
    expect(screen.getByText(`Followed ${s.transfers_followed} of ${s.transfers_seen} transfers seen`)).toBeInTheDocument()
    for (const r of s.not_followed) expect(screen.getByText(r.text)).toBeInTheDocument()
  })
})
