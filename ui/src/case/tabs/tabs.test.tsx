import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../../api/api'
import { ApiError } from '../../api/client'
import type { CaseDetail, VerifyResult } from '../../api/models'
import { readCase, readMock } from '../../test/files'
import { renderApp } from '../../test/render'
import { AuditTab } from './AuditTab'
import { InboundTab } from './InboundTab'
import { PatternsTab } from './PatternsTab'
import { TimelineTab } from './TimelineTab'
import { TransfersTab } from './TransfersTab'
import { WalletsTab } from './WalletsTab'

const hero = readCase<CaseDetail>('tron-coindcx')
const abstain = readCase<CaseDetail>('tron-abstain')
const ofac = readCase<CaseDetail>('tron-ofac')
const mockOkx = readMock<CaseDetail>('cases/demo-tron-okx.json')
const noop = () => {}

describe('TimelineTab', () => {
  it('heads each day with its date, and says how long passed between days', () => {
    renderApp(<TimelineTab c={hero} onSelect={noop} />)
    const days = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)
    expect(days).toEqual(['23 May 2025', '25 May 2025', '4 Jul 2025', '14 Jul 2025'])
    expect(screen.getByText('40 days later')).toBeInTheDocument()
    expect(screen.getByText('2 days later')).toBeInTheDocument()
  })

  it('tells each transfer in words: received, sent, forwarded, and after how long', () => {
    renderApp(<TimelineTab c={hero} onSelect={noop} />)
    const events = screen.getAllByTestId('timeline-event')
    expect(events).toHaveLength(8)
    expect(events[0]).toHaveTextContent(/18:43 UTC.*Received from.*Binance.*14 USDT/)
    expect(events[3]).toHaveTextContent(/Sent to.*CoinDCX.*1,530 USDT/)
    expect(events[3]).toHaveTextContent('1 d 8 h after funds last arrived')
    expect(events[7]).toHaveTextContent(/forwarded to/)
    expect(events[7]).toHaveTextContent('12 min after funds last arrived')
  })

  it('shows a pattern on the transfer that shows it', () => {
    renderApp(<TimelineTab c={hero} onSelect={noop} />)
    const events = screen.getAllByTestId('timeline-event')
    expect(within(events[6]).getByText('Lead')).toBeInTheDocument()
    expect(events.filter((e) => within(e).queryByText('Lead'))).toHaveLength(1)
  })

  it('links every transfer to its transaction and lets a wallet be selected', async () => {
    const onSelect = vi.fn()
    const { user } = renderApp(<TimelineTab c={hero} onSelect={onSelect} />)
    for (const e of hero.graph.edges) expect(screen.getByRole('group', { name: `Transaction ${e.tx_hash}` })).toBeInTheDocument()
    await user.click(within(screen.getAllByTestId('timeline-event')[3]).getByRole('button', { name: /^Show TCw8j3/ }))
    expect(onSelect).toHaveBeenCalledWith(hero.candidates[0].deposit_address)
  })

  it('says so when the case has no transfers', () => {
    renderApp(<TimelineTab c={{ ...hero, graph: { nodes: [], edges: [] }, typology_flags: [] }} onSelect={noop} />)
    expect(screen.getByText('No transfers were read for this wallet')).toBeInTheDocument()
  })
})

describe('TransfersTab', () => {
  it('lists every transfer with its amount and transaction', () => {
    renderApp(<TransfersTab c={hero} onSelect={noop} />)
    const table = screen.getByRole('table', { name: 'Transfers' })
    expect(within(table).getAllByRole('row')).toHaveLength(1 + hero.graph.edges.length)
    expect(within(table).getAllByText('In')).toHaveLength(5)
    expect(within(table).getAllByText('Out')).toHaveLength(3)
  })

  it('says when only part of a transfer is the wallet’s money', () => {
    const edges = hero.graph.edges.map((e, i) => (i === 0 ? { ...e, amount: 11000, traced_amount: 5800 } : e))
    renderApp(<TransfersTab c={{ ...hero, graph: { ...hero.graph, edges } }} onSelect={noop} />)
    expect(screen.getByText('of 11,000 USDT')).toBeInTheDocument()
  })
})

describe('WalletsTab', () => {
  it('lists every wallet in the graph with its role and label', () => {
    renderApp(<WalletsTab c={hero} selected={null} onSelect={noop} />)
    const table = screen.getByRole('table', { name: 'Wallets' })
    const rows = within(table).getAllByRole('row')
    expect(rows).toHaveLength(1 + hero.graph.nodes.length)
    expect(within(table).getByText('Suspect wallet')).toBeInTheDocument()
    expect(within(table).getByText('Deposit address')).toBeInTheDocument()
    expect(within(table).getByText('Busy wallet, where the trail stops')).toBeInTheDocument()
  })

  it('opens a wallet from its row: the keyboard’s way into the graph', async () => {
    const onSelect = vi.fn()
    const { user } = renderApp(<WalletsTab c={hero} selected={null} onSelect={onSelect} />)
    // rows read left to right, as the graph does: funders, the wallet, then hop by hop
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[3].textContent)).toEqual(['1 back', '1 back', '1 back', '0', '1', '1', '2'])
    const row = rows.find((r) => r.textContent?.includes('TCw8j3'))!
    row.focus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith(hero.graph.nodes[1].id)
  })
})

describe('PatternsTab', () => {
  it('lists the patterns with the wallet and the transactions, and keeps leads apart', () => {
    renderApp(<PatternsTab c={abstain} onSelect={noop} />)
    const patterns = screen.getByRole('region', { name: 'Patterns in the traced funds' })
    expect(within(patterns).getAllByText('Pattern')).toHaveLength(5)
    expect(within(patterns).getAllByText('Note')).toHaveLength(1)
    expect(within(patterns).queryByText('Lead')).not.toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Leads to check, in full' })).getAllByText('Lead')).toHaveLength(2)
    const first = abstain.typology_flags[0]
    expect(within(patterns).getByRole('group', { name: `Transaction ${first.tx_hashes[0]}` })).toBeInTheDocument()
  })

  it('puts an alert first', () => {
    renderApp(<PatternsTab c={ofac} onSelect={noop} />)
    const items = within(screen.getByRole('region', { name: 'Patterns in the traced funds' })).getAllByRole('listitem')
    expect(within(items[0]).getByText('Alert')).toBeInTheDocument()
  })

  it('says so when nothing was seen', () => {
    renderApp(<PatternsTab c={{ ...hero, typology_flags: [] }} onSelect={noop} />)
    expect(screen.getByText('No pattern was seen in the traced funds')).toBeInTheDocument()
  })
})

describe('InboundTab', () => {
  it('says what the wallet received and lists who paid it, largest first', () => {
    renderApp(<InboundTab c={hero} onSelect={noop} />)
    expect(screen.getByText(/The wallet received/)).toHaveTextContent('The wallet received 2,695 USDT in 5 transfers from 3 wallets')
    const rows = within(screen.getByRole('table', { name: 'Wallets that paid the suspect wallet' })).getAllByRole('row')
    expect(rows).toHaveLength(4)
    expect(rows[1]).toHaveTextContent(/TT9b4u.*3.*2,332 USDT/)
    expect(rows[3]).toHaveTextContent(/Binance.*1.*14 USDT/)
  })

  it('names an exchange that funded the wallet, in the backend’s words', () => {
    renderApp(<InboundTab c={hero} onSelect={noop} />)
    const funded = screen.getByRole('region', { name: 'Exchanges that funded the wallet' })
    expect(within(funded).getByText(/1% of the wallet's USDT \(14 USDT\) came from it in 1 hop/)).toBeInTheDocument()
  })

  it('says so when no inbound transfer was read', () => {
    renderApp(<InboundTab c={mockOkx} onSelect={noop} />)
    expect(screen.getByText('No inbound transfer was read')).toBeInTheDocument()
  })
})

describe('AuditTab', () => {
  it('shows the receipt: the fingerprint and digests whole, and what the run read', () => {
    renderApp(<AuditTab c={hero} />)
    const receipt = screen.getByRole('region', { name: 'Receipt' })
    const p = hero.provenance
    for (const digest of [p.findings_sha256!, p.content_sha256!, p.input_sha256!, p.responses_sha256!, p.label_db_sha256!, p.model_sha256!])
      expect(within(receipt).getByText(digest)).toBeInTheDocument()
    expect(within(receipt).getByText(/10 responses from api\.trongrid\.io, replayed from saved copies/)).toBeInTheDocument()
    expect(within(receipt).getByText('b5-bitcoin-1')).toBeInTheDocument()
    expect(within(receipt).getByText(p.notes[0])).toBeInTheDocument()
  })

  it('says a case stored before receipts existed has none', () => {
    const old = { ...hero, provenance: { ...hero.provenance, findings_sha256: null, content_sha256: null, input_sha256: null, responses_sha256: null, responses: null, pages: null } }
    renderApp(<AuditTab c={old} />)
    expect(screen.getByText(/stored before receipts existed/)).toBeInTheDocument()
  })

  it('verifies the case and shows the result and every check', async () => {
    const result: VerifyResult = {
      case_id: hero.id,
      matches: true,
      summary: 'Verified: the stored case, the 10 responses and the findings are the same.',
      checked_at: '2026-10-02T18:00:00Z',
      checks: [
        { name: 'stored_case', result: 'same', detail: 'The stored case still has its own fingerprint.' },
        { name: 'labels', result: 'different', detail: 'The label database changed since the case was traced.' },
        { name: 'model', result: 'not_checked', detail: 'No model was used.' },
      ],
    }
    vi.spyOn(api, 'verifyCase').mockResolvedValue(result)
    const { user } = renderApp(<AuditTab c={hero} />)
    await user.click(screen.getByRole('button', { name: 'Verify this case' }))
    expect(await screen.findByText(result.summary)).toBeInTheDocument()
    const checks = screen.getByRole('table', { name: 'Checks' })
    expect(within(checks).getAllByRole('row')).toHaveLength(4)
    expect(within(checks).getByText('Stored case')).toBeInTheDocument()
    expect(within(checks).getByText('Different')).toBeInTheDocument()
    expect(within(checks).getByText('Not checked')).toBeInTheDocument()
    expect(within(checks).getByText('The label database changed since the case was traced.')).toBeInTheDocument()
  })

  it('shows the server’s sentence when the case cannot be verified', async () => {
    vi.spyOn(api, 'verifyCase').mockRejectedValue(new ApiError(422, 'A demo fixture cannot be verified: it was not traced.'))
    const { user } = renderApp(<AuditTab c={hero} />)
    await user.click(screen.getByRole('button', { name: 'Verify this case' }))
    expect(await screen.findByText('A demo fixture cannot be verified: it was not traced.')).toBeInTheDocument()
  })

  it('lists who read, exported or verified the case', async () => {
    renderApp(<AuditTab c={mockOkx} />)
    const log = await screen.findByRole('table', { name: 'Access log of this case' })
    expect((await within(log).findAllByText('demo.officer')).length).toBe(3)
    expect(within(log).getByText('Exported the case file')).toBeInTheDocument()
    await waitFor(() => expect(within(log).getAllByRole('row')).toHaveLength(4))
  })
})

describe('the timeline of a large case', () => {
  it('shows the first 150 transfers, says how many there are, and shows more on request', async () => {
    const { bigCase } = await import('../../../scripts/big-graph.mjs')
    const big = bigCase(400)
    render(<TimelineTab c={big} onSelect={() => {}} />)
    const total = big.graph.edges.length
    expect(screen.getByText(`Showing the first 150 of ${total.toLocaleString('en-US')} transfers`)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show 150 more' }))
    expect(screen.getByText(`Showing the first 300 of ${total.toLocaleString('en-US')} transfers`)).toBeInTheDocument()
  })
})
