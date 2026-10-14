import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { FreezeMark, IssuerRequest } from '../api/models'
import { IssuerRequestPanel } from '../case/IssuerRequestPanel'
import { FREEZE_MEANING, FreezeChip, FreezeNote } from './FreezeChip'

// An ISIL Khorasan address of the recorded case tron-terror-link, as the freeze snapshot marks it.
const MARK: FreezeMark = {
  id: 'TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ',
  address: 'TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ',
  chain: 'tron',
  where: 'path',
  side: 'outbound',
  hop: 1,
  amount: 17060,
  asset: 'USDT',
  tx_hashes: ['abc'],
  issuer: 'Tether',
  frozen_asset: 'USDT',
  frozen_at: '2026-07-01T09:12:00Z',
  tx_hash: 'f00d',
  contract: 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t',
  text: 'Frozen by Tether on 1 Jul 2026',
}

describe('FreezeChip', () => {
  it('says who froze it and when, beside an icon, in the chain colour', () => {
    render(<FreezeChip mark={MARK} />)
    const chip = screen.getByText('Frozen by Tether on 1 Jul 2026').closest('[data-freeze]')!
    expect(chip.className).toContain('text-chain')
    expect(chip.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('says what a freeze does not establish, on focus', async () => {
    render(<FreezeChip mark={MARK} />)
    await userEvent.tab()
    expect(await screen.findByText(FREEZE_MEANING)).toBeInTheDocument()
    expect(screen.getByText(/Freezing transaction f00d/)).toBeInTheDocument()
  })
})

describe('FreezeNote', () => {
  it('lists each frozen wallet with where it sits and what reached it', () => {
    render(<FreezeNote marks={[MARK, { ...MARK, id: 'TCEe', address: 'TCEe', where: 'graph', amount: 15010 }]} />)
    const note = screen.getByRole('region', { name: 'Frozen by the issuer of USDT' })
    expect(within(note).getByText('2 wallets on this trace frozen by the issuer of USDT')).toBeInTheDocument()
    expect(within(note).getByText('On the Hop Rail')).toBeInTheDocument()
    expect(within(note).getByText('17,060 USDT reached it, 1 hop away')).toBeInTheDocument()
    expect(within(note).getByText(FREEZE_MEANING)).toBeInTheDocument()
  })

  it('leads with the wallet itself when the issuer froze it', () => {
    render(<FreezeNote marks={[{ ...MARK, where: 'origin', side: 'origin', hop: 0 }]} />)
    expect(screen.getByText('The issuer of USDT froze this wallet')).toBeInTheDocument()
  })

  it('draws nothing when no wallet is frozen', () => {
    const { container } = render(<FreezeNote marks={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
})

const REQUEST: IssuerRequest = {
  offered: true,
  reason: '1 address outside any exchange hold traced USDT. No exchange can be asked to act on them; the issuer can freeze USDT at an address.',
  draft: {
    watermark: 'Draft - officer review required',
    to: 'Tether (the issuer of USDT)',
    channel: 'Tether publishes no channel for submitting a request. For inquiries about its policies and procedures it gives inforequests@tether.to.',
    subject: 'Request to freeze USDT at 1 address - case FIR 9/2026',
    case_id: 'c1',
    case_ref: 'FIR 9/2026',
    chain: 'tron',
    traced_wallet: 'TSuspect',
    evidence_fingerprint: 'ab',
    paragraphs: ['p'],
    wallets: [
      {
        address: 'TDqSquXBgUCLYvYC4XZgrprLK589dkhSCf',
        chain: 'tron',
        hop: 2,
        role: 'held',
        received: 1122.22,
        held: 1122.22,
        busy: true,
        asset: 'USDT',
        first_seen: '2026-05-01T10:00:00Z',
        last_seen: '2026-05-01T10:00:00Z',
        tx_hashes: ['42c8'],
        label: null,
        frozen: null,
      },
    ],
    legal_provision: null,
    officer: null,
    policy: { title: 'Law Enforcement Requests Policy', publisher: 'Tether', url: 'https://tether.to/en/legal/?tab=law-enforcement-requests', updated: '3 January 2018', read: '14 October 2026', says: 's' },
    review_notes: ['Attach the legal process.', 'This tool sends nothing.'],
  },
}

describe('IssuerRequestPanel', () => {
  it('offers the draft as a PDF, lists the addresses and says nothing is sent', () => {
    render(
      <MemoryRouter>
        <IssuerRequestPanel request={REQUEST} caseId="c1" chain="tron" />
      </MemoryRouter>,
    )
    const panel = screen.getByRole('region', { name: 'Request to the issuer of USDT' })
    expect(within(panel).getByRole('link', { name: 'Open the draft (PDF)' })).toHaveAttribute('href', '/api/cases/c1/issuer-request.pdf')
    expect(within(panel).getByText(/nothing is sent/)).toBeInTheDocument()
    expect(within(panel).getByText(/probably a service/)).toBeInTheDocument()
    expect(within(panel).getByText('Funds stopped here, 2 hops out', { exact: false })).toBeInTheDocument()
  })

  it('draws nothing when no draft is offered', () => {
    const { container } = render(<IssuerRequestPanel request={{ offered: false, reason: 'r', draft: null }} caseId="c1" chain="tron" />)
    expect(container).toBeEmptyDOMElement()
  })
})
