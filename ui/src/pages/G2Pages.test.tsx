import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { CaseDetail, ComplaintStatus, PsCoverage, SahyogSim } from '../api/models'
import { toElements } from '../case/flowStyle'
import { RISK_BASIS } from '../components/RiskTag'
import { buildFlow } from '../lib/caseGraph'
import { readMock } from '../test/files'
import { renderApp } from '../test/render'

const open = (route: string) => renderApp(<AppRoutes />, { route })

// ---------------------------------------------------------------- coverage
describe('the problem statement coverage page', () => {
  const page = readMock<PsCoverage>('coverage.json')

  it('quotes every line word for word with its status, and counts them', async () => {
    open('/coverage')
    expect(await screen.findByRole('heading', { level: 1, name: 'Problem statement coverage' })).toBeInTheDocument()
    const tags = await screen.findAllByTestId('coverage-status')
    expect(tags).toHaveLength(page.total)
    for (const row of page.rows) expect(screen.getByText(row.text)).toBeInTheDocument()
    const counts = screen.getByRole('list', { name: 'Lines by status' })
    expect(counts).toHaveTextContent(`Built${page.counts.built}`)
    expect(counts).toHaveTextContent(`Partly built${page.counts.partly}`)
    expect(page.counts.built! + page.counts.partly! + page.counts.planned!).toBe(page.total)
  })

  it('says what is missing on every line that is not built, and where to see each line', async () => {
    open('/coverage')
    await screen.findAllByTestId('coverage-status')
    for (const row of page.rows.filter((r) => r.status !== 'built')) {
      const line = document.getElementById(row.id)!
      expect(line).toHaveTextContent('Not yet')
      expect(line).toHaveTextContent(row.gap!)
    }
    const built = page.rows.find((r) => r.status === 'built')!
    const line = document.getElementById(built.id)!
    expect(line).not.toHaveTextContent('Not yet')
    expect(within(line).getByRole('link', { name: built.where })).toHaveAttribute('href', built.where)
    expect(line).toHaveTextContent(built.evidence)
  })

  it('does not claim a chain the tool cannot trace', async () => {
    open('/coverage')
    await screen.findAllByTestId('coverage-status')
    const chains = page.rows.find((r) => r.id === 'multi-chain-mapping')!
    const missing = ['bsc', 'solana'].filter((c) => !page.traceable_chains.includes(c))
    expect(chains.status).toBe(missing.length ? 'partly' : 'built')
    const line = document.getElementById(chains.id)!
    expect(line).toHaveTextContent('Worked out from the chains that trace today, not typed.')
    if (missing.length) expect(line).toHaveTextContent('cannot be traced yet')
  })

  it('is one link away from the landing and from every screen', async () => {
    open('/')
    expect(await screen.findByRole('link', { name: 'Problem statement coverage' })).toHaveAttribute('href', '/coverage')
    expect(screen.getByRole('link', { name: 'problem statement, line by line' })).toHaveAttribute('href', '/coverage')
  })
})

// ---------------------------------------------------------------- simulator
describe('the SAHYOG simulator', () => {
  const sim = readMock<SahyogSim>('sahyog-sim.json')

  it('never lets the banner go: a simulator, not the portal', async () => {
    open('/sahyog-sim')
    const note = await screen.findByRole('note', { name: 'Simulator notice' })
    expect(note).toHaveTextContent('A simulator for demonstration. Not the SAHYOG portal.')
    expect(note).toHaveTextContent('Nothing leaves this installation.')
    expect(await screen.findByRole('heading', { level: 1, name: 'SAHYOG simulator' })).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull() // no emblem, no logo
  })

  it('shows a filed complaint with its status, the exchange named with its confidence, the risk class and the case', async () => {
    open('/sahyog-sim')
    const card = await screen.findByTestId('complaint')
    const c = sim.complaints[0]
    const w = c.wallets[0]
    expect(card).toHaveTextContent(c.complaint_ref)
    expect(within(card).getByRole('list', { name: 'Status: Result' })).toBeInTheDocument()
    expect(card).toHaveTextContent(w.top_vasp!)
    expect(card).toHaveTextContent('confidence')
    expect(within(card).getByTestId('risk-tag')).toHaveAttribute('data-risk', w.risk_class!)
    expect(within(card).getByRole('link', { name: 'Open the case' })).toHaveAttribute('href', `/cases/${w.case_id}`)
  })

  it('files a complaint through the intake with the fields of the contract', async () => {
    const filed: ComplaintStatus = { ...sim.complaints[0], complaint_ref: 'SIM-TEST-1', status: 'received' }
    const file = vi.spyOn(api, 'fileComplaint').mockResolvedValue(filed)
    const { user } = open('/sahyog-sim')
    const form = await screen.findByRole('form', { name: 'File a complaint' })
    await user.clear(within(form).getByLabelText('Complaint reference'))
    await user.type(within(form).getByLabelText('Complaint reference'), 'SIM-TEST-1')
    await user.type(within(form).getByLabelText('Wallet addresses'), 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c\n0x8971dd825ba5dd32b60307773f71f6e3efb0eda9')
    await user.type(within(form).getByLabelText(/Amount lost/), '2,50,000')
    await user.click(within(form).getByRole('button', { name: 'File complaint' }))
    await waitFor(() => expect(file).toHaveBeenCalledTimes(1))
    expect(file.mock.calls[0][0]).toMatchObject({
      complaint_ref: 'SIM-TEST-1',
      wallets: [{ address: 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' }, { address: '0x8971dd825ba5dd32b60307773f71f6e3efb0eda9' }],
      amount_lost_inr: 250000,
      category: 'investment_fraud',
    })
    expect(await screen.findByText('Complaint filed')).toBeInTheDocument()
  })

  it('asks for a wallet before filing, and shows the refusal as it came', async () => {
    const file = vi.spyOn(api, 'fileComplaint').mockRejectedValue(new ApiError(422, 'No wallet in this complaint could be accepted. nope: Could not tell which chain this address is on.'))
    const { user } = open('/sahyog-sim')
    const form = await screen.findByRole('form', { name: 'File a complaint' })
    await user.click(within(form).getByRole('button', { name: 'File complaint' }))
    expect(within(form).getByRole('alert')).toHaveTextContent('Give at least one wallet address')
    expect(file).not.toHaveBeenCalled()
    await user.type(within(form).getByLabelText('Wallet addresses'), 'nope')
    await user.click(within(form).getByRole('button', { name: 'File complaint' }))
    expect(await within(form).findByRole('alert')).toHaveTextContent('No wallet in this complaint could be accepted.')
  })

  it('plays the exchange: only the replies that can follow are offered, and each goes through the reply leg', async () => {
    const reply = vi.spyOn(api, 'simReply').mockResolvedValue({ request_id: sim.requests[0].id, status: 'freeze_confirmed', recorded_at: '2026-10-05T00:00:00Z', location: null })
    const { user } = open('/sahyog-sim')
    const card = await screen.findByTestId('sim-request')
    const r = sim.requests[0]
    expect(card).toHaveTextContent(r.reference)
    const group = within(card).getByRole('group', { name: `Reply as ${r.vasp}` })
    expect(within(group).getAllByRole('button')).toHaveLength(r.allowed_replies.length)
    await user.click(within(group).getByRole('button', { name: 'Confirm freeze' }))
    await waitFor(() => expect(reply).toHaveBeenCalledWith(r.id, expect.objectContaining({ status: 'freeze_confirmed' })))
    expect(await screen.findByText('Freeze confirmed')).toBeInTheDocument()
  })

  it('says so when no intake key is set', async () => {
    vi.spyOn(api, 'sahyogSim').mockResolvedValue({ ...sim, enabled: false, why_disabled: 'No SAHYOG API key is configured on this installation.', complaints: [], requests: [] })
    open('/sahyog-sim')
    expect(await screen.findByText('The simulator is switched off')).toBeInTheDocument()
    expect(screen.getByRole('note', { name: 'Simulator notice' })).toBeInTheDocument()
    expect(screen.queryByRole('form')).toBeNull()
  })
})

// ---------------------------------------------------------------- risk
describe('risk on a case', () => {
  const sanctioned = readMock<CaseDetail>('cases/demo-tron-sanctioned.json')
  const quiet = readMock<CaseDetail>('cases/demo-tron-okx.json')

  it('shows the wallet and flow class under the rail and says what the score is', async () => {
    open(`/cases/${sanctioned.id}`)
    const line = await screen.findByLabelText('Risk class')
    const [wallet, flow] = within(line).getAllByTestId('risk-tag')
    expect(wallet).toHaveAttribute('data-risk', sanctioned.risk!.risk_class!)
    expect(wallet).toHaveTextContent(`${sanctioned.risk!.score}/100`)
    expect(flow).toHaveTextContent('flow risk')
    expect(line).toHaveTextContent(RISK_BASIS)
  })

  it('lists each indicator with its points and its sentence in the Risk tab', async () => {
    open(`/cases/${sanctioned.id}?tab=risk`)
    const meter = await screen.findByRole('meter', { name: 'Risk score' })
    expect(meter).toHaveAttribute('aria-valuenow', String(sanctioned.risk!.score))
    const list = screen.getByRole('list', { name: 'Indicators present' })
    for (const i of sanctioned.risk!.indicators) {
      expect(within(list).getByText(i.name)).toBeInTheDocument()
      expect(within(list).getByText(`+${i.points}`)).toBeInTheDocument()
      expect(within(list).getByText(i.text)).toBeInTheDocument()
    }
    expect(screen.getByText(/Transaction flows: the path on the Hop Rail is/)).toBeInTheDocument()
  })

  it('gives every transfer a class in the Transfers tab', async () => {
    open(`/cases/${sanctioned.id}?tab=transfers`)
    const table = await screen.findByRole('table', { name: 'Transfers' })
    expect(within(table).getByRole('columnheader', { name: /Flow risk/ })).toBeInTheDocument()
    const tags = within(table).getAllByTestId('risk-tag')
    expect(tags).toHaveLength(sanctioned.graph.edges.length)
    const flagged = sanctioned.risk!.flows
    expect(flagged.length).toBeGreaterThan(0)
    expect(tags.filter((t) => t.getAttribute('data-risk') !== 'low')).toHaveLength(flagged.length)
    expect(table).toHaveTextContent(flagged[0].reasons[0])
  })

  it('marks a flagged transfer on the graph with a symbol and its class in words, not colour alone', () => {
    const flows = new Map(sanctioned.risk!.flows.map((f) => [f.edge_id, f]))
    const edges = toElements(buildFlow(sanctioned), flows).filter((e) => e.group === 'edges')
    const marked = edges.filter((e) => e.data.risk)
    expect(marked.length).toBeGreaterThan(0)
    for (const e of marked) expect(e.data.label).toMatch(/^▲ (Medium|High|Severe) risk\n/)
    const plain = toElements(buildFlow(quiet), new Map()).filter((e) => e.group === 'edges')
    expect(plain.every((e) => !e.data.risk && !String(e.data.label).includes('▲'))).toBe(true)
  })

  it('says a case came through SAHYOG when it did', async () => {
    vi.spyOn(api, 'case').mockResolvedValue({ ...quiet, sahyog_complaint_ref: 'NCRP-2026-0001' })
    open(`/cases/${quiet.id}`)
    expect(await screen.findByText(/Reported through SAHYOG/)).toHaveTextContent('Reported through SAHYOG · NCRP-2026-0001')
  })
})

describe('risk on the lists', () => {
  it('counts the cases by risk class on the dashboard, each count a link to its list', async () => {
    open('/dashboard')
    const panel = await screen.findByRole('region', { name: 'Cases by risk class' })
    expect(panel).toHaveTextContent(RISK_BASIS)
    expect(within(panel).getAllByTestId('risk-tag').map((t) => t.getAttribute('data-risk'))).toEqual(['severe', 'high', 'medium', 'low'])
    expect(within(panel).getAllByRole('link').some((a) => a.getAttribute('href') === '/cases?risk=severe')).toBe(true)
  })

  it('filters the cases list by risk class', async () => {
    open('/cases?risk=severe')
    const table = await screen.findByRole('table')
    const tags = await within(table).findAllByTestId('risk-tag')
    expect(tags.length).toBeGreaterThan(0)
    expect(tags.every((t) => t.getAttribute('data-risk') === 'severe')).toBe(true)
  })
})
