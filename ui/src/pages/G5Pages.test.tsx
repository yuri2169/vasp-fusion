import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { BatchDetail, CaseDetail, ScaleMetrics } from '../api/models'
import { readMock } from '../test/files'
import { renderApp } from '../test/render'
import { progressSentence, tracedBy } from './BatchPage'

const open = (route: string) => renderApp(<AppRoutes />, { route })
const batch = readMock<BatchDetail>('batches/b-demo.json')

// ---------------------------------------------------------------- a batch
describe('a batch', () => {
  it('shows every uploaded row with its result, proximity and confidence apart', async () => {
    open('/batch/b-demo')
    expect(await screen.findByRole('heading', { level: 1, name: batch.name! })).toBeInTheDocument()
    const table = await screen.findByRole('table', { name: 'Batch results' })
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows).toHaveLength(batch.rows.length)
    const named = batch.rows.find((r) => r.top_vasp)!
    const line = rows[batch.rows.indexOf(named)]
    expect(within(line).getByRole('link', { name: named.address })).toHaveAttribute('href', named.case_url)
    expect(line).toHaveTextContent(named.top_vasp!)
    expect(line).toHaveTextContent(String(named.hops))
    expect(screen.getByRole('columnheader', { name: /Hops/ })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Confidence/ })).toBeInTheDocument()
  })

  it('keeps a refused row, with the reason it was refused', async () => {
    open('/batch/b-demo')
    const table = await screen.findByRole('table', { name: 'Batch results' })
    const bad = batch.rows.find((r) => !r.accepted)!
    const line = within(table).getAllByRole('row')[batch.rows.indexOf(bad) + 1]
    expect(line).toHaveTextContent('Refused')
    expect(line).toHaveTextContent(bad.error!)
    expect(within(line).queryByRole('link')).toBeNull()
    expect(screen.getByRole('list', { name: 'The batch in counts' })).toHaveTextContent(`Rows refused${batch.progress.refused}`)
  })

  it('says how far the queue has got, and offers the table as a file', async () => {
    open('/batch/b-demo')
    expect(await screen.findByText(progressSentence(batch.progress))).toHaveAttribute('role', 'status')
    const bar = screen.getByRole('progressbar', { name: 'Wallets traced' })
    expect(bar).toHaveAttribute('aria-valuenow', String(batch.progress.done + batch.progress.failed))
    expect(bar).toHaveAttribute('aria-valuemax', String(batch.progress.accepted))
    expect(screen.getByRole('link', { name: /Download results/ })).toHaveAttribute('href', '/api/batches/b-demo/results.csv')
  })

  it('words a running batch and a batch with nothing to trace', () => {
    const p = { ...batch.progress, accepted: 10, done: 3, failed: 1, running: 2, queued: 4, finished: false }
    expect(progressSentence(p)).toBe('4 of 10 wallets traced, 2 being traced now, 4 waiting.')
    expect(progressSentence({ ...p, done: 9, failed: 1, running: 0, queued: 0, finished: true })).toBe('All 10 wallets traced, 1 of them failed.')
    expect(progressSentence({ ...p, accepted: 0 })).toBe('No row could be traced. Each row says why.')
    expect(tracedBy(4)).toBe('4 worker processes')
    expect(tracedBy(1)).toBe('1 worker process')
    expect(tracedBy(0)).toBe('the server process, one wallet at a time')
  })

  it('says so when it cannot be read', async () => {
    vi.spyOn(api, 'batch').mockRejectedValue(new ApiError(404, 'No batch has the id b-nope. Open the batch list to find it.'))
    open('/batch/b-nope')
    expect(await screen.findByText('No batch has the id b-nope. Open the batch list to find it.')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------- uploading
describe('uploading a batch', () => {
  it('sends the pasted lines with the budget and opens the batch', async () => {
    const upload = vi.spyOn(api, 'uploadBatch')
    const { user } = open('/batch')
    const button = await screen.findByRole('button', { name: 'Upload and trace' })
    expect(button).toBeDisabled()
    await user.type(screen.getByLabelText('Or paste the lines'), 'Tabc,tron,FIR 1{enter}0xdef')
    await user.type(screen.getByLabelText(/^Name/), 'Complaint 14')
    await user.clear(screen.getByLabelText('Wallets read per direction'))
    await user.type(screen.getByLabelText('Wallets read per direction'), '200')
    expect(screen.getByText(/^2 lines/)).toBeInTheDocument()
    await user.click(button)
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/batch/b-demo'))
    expect(upload).toHaveBeenCalledWith({ csv: 'Tabc,tron,FIR 1\n0xdef', name: 'Complaint 14', max_hops: 3, max_wallets: 200 })
  })

  it('refuses a budget outside 1 to 2,000 before anything is sent', async () => {
    const { user } = open('/batch')
    await user.type(await screen.findByLabelText('Or paste the lines'), 'Tabc')
    const budget = screen.getByLabelText('Wallets read per direction')
    await user.clear(budget)
    await user.type(budget, '5000')
    expect(screen.getByText('A whole number from 1 to 2,000.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload and trace' })).toBeDisabled()
  })

  it('shows the server’s sentence when the upload is refused', async () => {
    vi.spyOn(api, 'uploadBatch').mockRejectedValue(new ApiError(422, 'The upload holds no wallet. Give one address per line.'))
    const { user } = open('/batch')
    await user.type(await screen.findByLabelText('Or paste the lines'), 'address')
    await user.click(screen.getByRole('button', { name: 'Upload and trace' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The upload holds no wallet. Give one address per line.')
  })

  it('lists earlier batches and is one link away from the cases', async () => {
    open('/batch')
    const earlier = await screen.findByRole('region', { name: 'Earlier batches' })
    expect(await within(earlier).findByRole('link', { name: new RegExp(batch.name!) })).toHaveAttribute('href', '/batch/b-demo')
    open('/cases')
    expect((await screen.findAllByRole('link', { name: 'Trace a batch' }))[0]).toHaveAttribute('href', '/batch')
  })
})

// ---------------------------------------------------------------- the budget on a case
describe('the trace budget', () => {
  const cases = readMock<{ items: { id: string }[] }>('cases.json')
  const id = cases.items[0].id
  const stored = readMock<CaseDetail>(`cases/${id}.json`)
  const text = 'The budget, not the evidence, ended this trace: it reached its budget of 40 wallets on the way out. 12% of the funds (120 USDT) is in wallets it did not read. Trace the wallet again with a larger budget to follow them.'

  it('is said on the case when it, not the evidence, ended the trace', async () => {
    vi.spyOn(api, 'case').mockResolvedValue({
      ...stored,
      provenance: { ...stored.provenance, budget: { max_wallets: 40, max_hops: 3, max_seconds: null, ended_by: 'wallets', ended_side: 'outbound', wallets_read: 40, share_not_followed: 0.12, text } },
    })
    open(`/cases/${id}`)
    expect(await screen.findByRole('note', { name: 'Trace budget' })).toHaveTextContent(text)
  })

  it('is not mentioned when the evidence ended the trace', async () => {
    open(`/cases/${id}`)
    await screen.findByRole('heading', { level: 1 })
    await waitFor(() => expect(screen.queryByRole('progressbar')).toBeNull())
    expect(screen.queryByRole('note', { name: 'Trace budget' })).toBeNull()
  })

  it('is sent with a new case only when the officer changed it', async () => {
    const openCase = vi.spyOn(api, 'openCase')
    const address = readMock<CaseDetail>(`cases/${id}.json`).address
    const { user } = open('/cases/new')
    const form = await screen.findByRole('form', { name: 'Open a case' })
    await user.type(within(form).getByLabelText('Wallet address'), address)
    const budget = screen.getByLabelText('Wallets read per direction')
    expect(budget).toHaveValue('40')
    await user.clear(budget)
    await user.type(budget, '300')
    await user.click(within(form).getByRole('button', { name: 'Trace wallet' }))
    await waitFor(() => expect(openCase).toHaveBeenCalled())
    expect(openCase.mock.calls[0][0]).toMatchObject({ address, max_wallets: 300 })
  })
})

// ---------------------------------------------------------------- measured throughput
describe('the measured throughput on the model page', () => {
  const scale = readMock<ScaleMetrics>('scale.json')

  it('shows the figures of the bench file, with the machine and what limits them', async () => {
    open('/model')
    const panel = await screen.findByRole('region', { name: 'Throughput: wallets traced per minute' })
    if (scale.status !== 'measured') {
      expect(await within(panel).findByText(/Not yet measured on this installation/)).toBeInTheDocument()
      return
    }
    const table = await within(panel).findByRole('table', { name: 'Throughput by number of worker processes' })
    expect(within(table).getAllByRole('row').slice(1)).toHaveLength(scale.runs.length)
    for (const run of scale.runs)
      expect(table).toHaveTextContent(run.cases_per_minute.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }))
    expect(panel).toHaveTextContent(scale.machine!)
    expect(panel).toHaveTextContent(scale.measured_on!)
    for (const limit of scale.limits) expect(panel).toHaveTextContent(limit)
    expect(panel).toHaveTextContent('make bench-scale')
  })

  it('shows no figure when nothing was measured', async () => {
    vi.spyOn(api, 'scale').mockResolvedValue({ status: 'not_measured', runs: [], limits: [], notes: [] })
    open('/model')
    const panel = await screen.findByRole('region', { name: 'Throughput: wallets traced per minute' })
    expect(await within(panel).findByText(/Not yet measured on this installation/)).toBeInTheDocument()
    expect(within(panel).queryByRole('table')).toBeNull()
  })
})
