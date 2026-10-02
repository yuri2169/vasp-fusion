import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import type { CaseDetail, CaseSummary } from '../api/models'
import { mockSettings } from '../api/mock'
import { readCase } from '../test/files'
import { renderApp } from '../test/render'

const hero = readCase<CaseDetail>('tron-coindcx')
const DEMO_TRON = 'TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR' // mocks/cases/demo-tron-okx.json

const open = (route: string) => renderApp(<AppRoutes />, { route })
const where = () => screen.getByTestId('location').textContent
const serve = (c: CaseDetail) => vi.spyOn(api, 'case').mockResolvedValue(c)

describe('a case that names an exchange', () => {
  it('shows the wallet, the Hop Rail ending in the stamp, the graph, the answer and the tabs', async () => {
    open('/cases/demo-tron-okx')
    expect(await screen.findByRole('heading', { level: 1, name: /TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR/ })).toBeInTheDocument()
    const rail = screen.getByRole('list', { name: 'Path of the funds' })
    expect(within(rail).getByTestId('outcome-stamp')).toHaveAttribute('data-outcome', 'ATTRIBUTED')
    expect(screen.getByRole('heading', { level: 2, name: 'Fund flow' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Why OKX?' })).toBeInTheDocument()
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Timeline', 'Transfers 7', 'Wallets 8', 'Patterns 1', 'Inbound funding', 'Audit'])
  })

  it('has one primary action: draft the request', async () => {
    open('/cases/demo-tron-okx')
    const links = await screen.findAllByRole('link', { name: /^Draft request to/ })
    expect(links).toHaveLength(1)
    expect(links[0]).toHaveAttribute('href', '/desk?vasp=OKX&case=demo-tron-okx')
  })

  it('says what the officer entered: reference, complaint, loss, the day it was opened, and that it is demo data', async () => {
    open('/cases/demo-tron-okx')
    const header = (await screen.findByRole('heading', { level: 1 })).closest('header')!
    expect(header).toHaveTextContent('Case DEMO/2026/001')
    expect(header).toHaveTextContent('Complaint 31509260001234')
    expect(header).toHaveTextContent('Reported loss ₹40,50,000')
    expect(header).toHaveTextContent('Opened 13 Sep 2026')
    expect(within(header).getByText('Demo')).toBeInTheDocument()
  })

  it('shows where the funds went, inside the rail’s card, for a real case', async () => {
    serve(hero)
    open('/cases/tron-coindcx')
    expect(await screen.findByText('Where the 2,652.22 USDT went')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Why CoinDCX?' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Inbound funding 5' })).toBeInTheDocument()
  })
})

describe('the other two outcomes', () => {
  it('INSUFFICIENT EVIDENCE is its own screen: no exchange, no request, what would change it', async () => {
    open('/cases/demo-eth-abstain')
    expect(await screen.findByRole('heading', { level: 2, name: 'No exchange is named' })).toBeInTheDocument()
    expect(within(screen.getByRole('list', { name: 'Path of the funds' })).getByTestId('outcome-stamp')).toHaveAttribute('data-outcome', 'INSUFFICIENT_EVIDENCE')
    expect(screen.getByRole('region', { name: 'What would change this' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
  })

  it('a sanctioned result leads with the alert', async () => {
    open('/cases/demo-tron-sanctioned')
    expect(await screen.findByRole('heading', { level: 2, name: 'Sanctioned address reached' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
  })
})

describe('the tabs', () => {
  it('opens on the timeline, and keeps the open tab in the address', async () => {
    const { user } = open('/cases/demo-tron-okx')
    expect(await screen.findByRole('tabpanel', { name: 'Timeline' })).toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Transfers 7' }))
    expect(screen.getByRole('table', { name: 'Transfers' })).toBeInTheDocument()
    expect(where()).toBe('/cases/demo-tron-okx?tab=transfers')
  })

  it('opens the tab the address names', async () => {
    open('/cases/demo-tron-okx?tab=audit')
    expect(await screen.findByRole('region', { name: 'Receipt' })).toBeInTheDocument()
  })
})

describe('selecting a wallet', () => {
  it('from the Wallets tab: opens it beside the graph, marks its path on the rail, and keeps it in the address', async () => {
    const { user } = open('/cases/demo-tron-okx?tab=wallets')
    const table = await screen.findByRole('table', { name: 'Wallets' })
    await user.click(within(table).getByRole('button', { name: /^Show TPJMWH/ }))

    expect(screen.getByRole('heading', { level: 2, name: 'Wallet on the trail' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Why OKX?' })).not.toBeInTheDocument()
    expect(where()).toMatch(/wallet=TPJMWH/)

    const chips = within(screen.getByRole('list', { name: 'Path of the funds' })).getAllByRole('group', { name: /Tron address/ })
    expect(chips.map((c) => c.dataset.marked)).toEqual(['true', 'true', 'true', undefined])
    expect(chips.map((c) => c.dataset.selected)).toEqual([undefined, undefined, 'true', undefined])
  })

  it('goes back to the answer', async () => {
    const { user } = open('/cases/demo-tron-okx?wallet=TPJMWH7VNhGgj4a6osPAVKedxaFwAJLWZz')
    await user.click(await screen.findByRole('button', { name: 'Back to the answer' }))
    expect(screen.getByRole('heading', { level: 2, name: 'Why OKX?' })).toBeInTheDocument()
    expect(where()).toBe('/cases/demo-tron-okx')
  })

  it('from the Hop Rail', async () => {
    const { user } = open('/cases/demo-tron-okx')
    const rail = await screen.findByRole('list', { name: 'Path of the funds' })
    await user.click(within(rail).getByRole('button', { name: /^Show THS5KL/ }))
    expect(screen.getByRole('heading', { level: 2, name: 'Deposit address' })).toBeInTheDocument()
  })
})

describe('a trace in progress', () => {
  it('says what is known, then extends the rail hop by hop when the result arrives', async () => {
    mockSettings.traceMs = 400
    await api.openCase({ address: DEMO_TRON })
    open('/cases/demo-tron-okx')

    expect(await screen.findByRole('heading', { level: 2, name: 'Tracing the wallet' })).toBeInTheDocument()
    expect(screen.getByText('Tracing…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Stop waiting' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Fund flow' })).not.toBeInTheDocument()

    expect(await screen.findByRole('heading', { level: 2, name: 'Why OKX?' }, { timeout: 4000 })).toBeInTheDocument()
    const rail = screen.getByRole('list', { name: 'Path of the funds' })
    expect(rail.querySelectorAll('.rail-step').length).toBe(4)
    expect(rail.querySelector('.rail-stamp')).not.toBeNull()
    expect(screen.getByText(/^Trace finished\. It read 3 responses and found 8 wallets and 7 transfers\.$/)).toBeInTheDocument()
  })

  it('does not animate a case that was already finished when it was opened', async () => {
    open('/cases/demo-tron-okx')
    const rail = await screen.findByRole('list', { name: 'Path of the funds' })
    expect(rail.querySelector('.rail-step')).toBeNull()
    expect(screen.queryByText(/^Trace finished/)).not.toBeInTheDocument()
  })

  it('lets the officer stop waiting; the trace goes on and the case stays in the list', async () => {
    mockSettings.traceMs = 5000
    await api.openCase({ address: DEMO_TRON })
    const { user } = open('/cases/demo-tron-okx')
    await user.click(await screen.findByRole('button', { name: 'Stop waiting' }))
    expect(where()).toBe('/cases')
    expect(await screen.findByText('Stopped waiting')).toBeInTheDocument()
    mockSettings.traceMs = 0
    await api.openCase({ address: DEMO_TRON }) // ends the mock trace for the tests after this one
  })

  it('keeps the previous result on screen while the wallet is traced again', async () => {
    serve({ ...hero, status: 'running' })
    open('/cases/tron-coindcx')
    expect(await screen.findByText(/Tracing again\. This is the previous result/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Why CoinDCX?' })).toBeInTheDocument()
  })
})

describe('a trace that failed', () => {
  const failed: CaseDetail = {
    ...hero,
    status: 'failed',
    outcome: null,
    top_vasp: null,
    confidence: null,
    error: 'CacheMiss: OFFLINE=1 and not cached: api.trongrid.io',
    hop_rail: [],
    graph: { nodes: [], edges: [] },
    candidates: [],
    typology_flags: [],
    where_funds_went: [],
    narrative: '',
    next_steps: [],
  }

  it('says why, in the server’s words, and offers to trace again', async () => {
    serve(failed)
    const openCase = vi.spyOn(api, 'openCase').mockResolvedValue({ id: hero.id, status: 'queued' } as CaseSummary)
    const { user } = open('/cases/tron-coindcx')
    expect(await screen.findByText('The trace failed')).toBeInTheDocument()
    expect(screen.getByText('CacheMiss: OFFLINE=1 and not cached: api.trongrid.io')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Trace again' }))
    await waitFor(() => expect(openCase).toHaveBeenCalledWith({ address: hero.address, chain: 'tron', max_hops: 3 }, true))
  })
})

describe('trace again', () => {
  it('asks first, lets the hop limit be changed, then traces with refresh', async () => {
    serve(hero)
    const openCase = vi.spyOn(api, 'openCase').mockResolvedValue({ id: hero.id, status: 'queued' } as CaseSummary)
    const { user } = open('/cases/tron-coindcx')
    await user.click(await screen.findByRole('button', { name: 'Trace again' }))

    const dialog = screen.getByRole('dialog', { name: 'Trace this wallet again?' })
    expect(within(dialog).getByRole('radio', { name: '3 hops' })).toBeChecked()
    await user.click(within(dialog).getByRole('radio', { name: '4 hops' }))
    await user.click(within(dialog).getByRole('button', { name: 'Trace again' }))

    await waitFor(() => expect(openCase).toHaveBeenCalledWith({ address: hero.address, chain: 'tron', max_hops: 4 }, true))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })
})

describe('a case that cannot be opened', () => {
  it('shows the server’s sentence', async () => {
    open('/cases/nope')
    expect(await screen.findByText('This case could not be opened')).toBeInTheDocument()
    expect(screen.getByText(/no demo fixture/i)).toBeInTheDocument()
  })
})
