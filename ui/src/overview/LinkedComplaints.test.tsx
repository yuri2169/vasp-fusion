import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { SharedWallet } from '../api/models'
import { renderApp } from '../test/render'
import { LINK_LIMIT, RelatedCasesPanel } from './LinkedComplaints'

// The one wallet the recorded Tron cases share: a busy unlabelled wallet (amounts as traced).
const HUB: SharedWallet = {
  address: 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf',
  chain: 'tron',
  label: null,
  flags: [],
  busy: true,
  suspects: 2,
  cases: [
    { case_id: 'tron-coindcx', case_ref: 'DEMO/2026/101', suspect: 'TYJD', hop: 2, amount: 1122.22, asset: 'USDT', first_arrival: null, is_suspect: false },
    { case_id: 'tron-abstain', case_ref: 'DEMO/2026/105', suspect: 'TXXv', hop: 2, amount: 721, asset: 'USDT', first_arrival: null, is_suspect: false },
  ],
}

describe('RelatedCasesPanel', () => {
  it('names the other cases, how far and how much, and says what a link does not establish', () => {
    renderApp(<RelatedCasesPanel links={[{ ...HUB, flags: ['Frozen by Tether on 2 Apr 2026'] }]} caseId="tron-coindcx" />)
    const panel = screen.getByRole('region', { name: 'Related cases' })
    expect(within(panel).getByText('This trace shares 1 wallet with 1 other case.')).toBeInTheDocument()
    expect(within(panel).getByText(LINK_LIMIT)).toBeInTheDocument()
    expect(within(panel).getByText('This case')).toBeInTheDocument()
    expect(within(panel).getByRole('link', { name: 'Case DEMO/2026/105' })).toHaveAttribute('href', '/cases/tron-abstain')
    expect(within(panel).getByText('721 USDT')).toBeInTheDocument()
    expect(within(panel).getByText(/most likely a service/)).toBeInTheDocument()
    expect(within(panel).getByText('Frozen by Tether on 2 Apr 2026').className).toContain('text-chain')
  })

  it('draws nothing when the trace shares no wallet', () => {
    const { container } = renderApp(<RelatedCasesPanel links={[]} caseId="x" />)
    expect(container.querySelector('[data-related]')).toBeNull()
  })
})
