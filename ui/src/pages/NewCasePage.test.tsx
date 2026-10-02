import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { CaseSummary } from '../api/models'
import { renderApp } from '../test/render'

const DEMO_TRON = 'TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR' // mocks/cases/demo-tron-okx.json
const REAL_TRON = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c'
const REAL_EVM = '0x8971dd825ba5dd32b60307773f71f6e3efb0eda9'

const open = () => renderApp(<AppRoutes />, { route: '/cases/new' })
const form = () => screen.getByRole('form', { name: 'Open a case' })
const address = () => within(form()).getByLabelText('Wallet address')
const trace = () => within(form()).getByRole('button', { name: 'Trace wallet' })
const where = () => screen.getByTestId('location').textContent
const opened = (id = 'c-0123456789', status: CaseSummary['status'] = 'queued') =>
  vi.spyOn(api, 'openCase').mockResolvedValue({ id, status } as CaseSummary)

describe('opening a case', () => {
  it('asks for the wallet first, and cannot trace nothing', async () => {
    open()
    expect(await screen.findByRole('heading', { level: 1, name: 'Open a case' })).toBeInTheDocument()
    expect(trace()).toBeDisabled()
  })

  it('names the chain of a valid address and lets it be traced', async () => {
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    expect(within(form()).getByText('TRON')).toBeInTheDocument()
    expect(trace()).toBeEnabled()
  })

  it('catches a typo before any trace, and says what is wrong', async () => {
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON.slice(0, -1) + 'd')
    expect(address()).toHaveAttribute('aria-invalid', 'true')
    expect(within(form()).getByText(/checksum|typo|not a valid/i)).toBeInTheDocument()
    expect(trace()).toBeDisabled()
  })

  it('sends only the wallet and the hop limit when nothing else is filled in', async () => {
    const openCase = opened()
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    await user.click(trace())
    await waitFor(() => expect(openCase).toHaveBeenCalledWith({ address: REAL_TRON, chain: 'tron', max_hops: 3 }, false))
    await waitFor(() => expect(where()).toBe('/cases/c-0123456789'))
  })

  it('sends the complaint’s details as the officer typed them: trimmed, the amount as a number', async () => {
    const openCase = opened()
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), `  ${REAL_TRON} `)
    await user.type(within(form()).getByLabelText('Case reference'), ' CC/2026/118 ')
    await user.type(within(form()).getByLabelText('Complaint number'), '31509260001234')
    await user.type(within(form()).getByLabelText('Amount lost'), '40,50,000')
    await user.type(within(form()).getByLabelText('Date of the incident'), '2026-09-13')
    await user.click(within(form()).getByRole('radio', { name: '4 hops' }))
    await user.click(trace())
    await waitFor(() =>
      expect(openCase).toHaveBeenCalledWith(
        {
          address: REAL_TRON,
          chain: 'tron',
          case_ref: 'CC/2026/118',
          complaint_no: '31509260001234',
          amount_lost_inr: 4050000,
          incident_date: '2026-09-13',
          max_hops: 4,
        },
        false,
      ),
    )
  })

  it('refuses an amount that is not a number, and a date in the future', async () => {
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    await user.type(within(form()).getByLabelText('Amount lost'), 'forty lakh')
    expect(within(form()).getByText('Write the amount in rupees, in digits: 4050000 or 40,50,000.')).toBeInTheDocument()
    expect(trace()).toBeDisabled()
    await user.clear(within(form()).getByLabelText('Amount lost'))
    expect(trace()).toBeEnabled()

    await user.type(within(form()).getByLabelText('Date of the incident'), '2999-01-01')
    expect(within(form()).getByText('The incident cannot be in the future.')).toBeInTheDocument()
    expect(trace()).toBeDisabled()
  })

  it('offers the EVM chains for an 0x address', async () => {
    const openCase = opened()
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_EVM)
    await user.selectOptions(within(form()).getByLabelText('Chain'), 'polygon')
    await user.click(trace())
    await waitFor(() => expect(openCase).toHaveBeenCalledWith({ address: REAL_EVM, chain: 'polygon', max_hops: 3 }, false))
  })

  it('traces again on request when the wallet already has a case', async () => {
    const openCase = opened()
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    await user.click(within(form()).getByRole('checkbox', { name: /Trace again if this wallet already has a case/ }))
    await user.click(trace())
    await waitFor(() => expect(openCase).toHaveBeenCalledWith({ address: REAL_TRON, chain: 'tron', max_hops: 3 }, true))
  })

  it('says so when the wallet already has a case and it was not traced again', async () => {
    opened('tron-coindcx', 'done')
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    await user.click(trace())
    expect(await screen.findByText('This wallet already has a case')).toBeInTheDocument()
  })

  it('does not say a trace finished when the stored case was only opened', async () => {
    opened('demo-tron-okx', 'done')
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    await user.click(trace())
    expect(await screen.findByRole('heading', { level: 2, name: 'Why OKX?' })).toBeInTheDocument()
    expect(screen.queryByText(/^Trace finished/)).not.toBeInTheDocument()
    expect(document.querySelector('.rail-step')).toBeNull()
  })

  it('shows the server’s sentence when the case cannot be opened', async () => {
    vi.spyOn(api, 'openCase').mockRejectedValue(new ApiError(503, 'The label database is missing. Run make labels, then try again.'))
    const { user } = open()
    await screen.findByRole('heading', { level: 1 })
    await user.type(address(), REAL_TRON)
    await user.click(trace())
    expect(await within(form()).findByRole('alert')).toHaveTextContent('The label database is missing. Run make labels, then try again.')
    expect(where()).toBe('/cases/new')
  })
})

describe('the recorded demo cases', () => {
  it('lists them beside the sheet, and picking one fills in its wallet', async () => {
    const { user } = open()
    const demos = await screen.findByRole('region', { name: 'Recorded demo cases' })
    const picks = await within(demos).findAllByRole('button')
    expect(picks).toHaveLength(3)
    await user.click(within(demos).getByRole('button', { name: /DEMO\/2026\/001/ }))
    expect(address()).toHaveValue(DEMO_TRON)
    expect(trace()).toBeEnabled()
  })

  it('then traces it like any wallet, and opens the case', async () => {
    const { user } = open()
    const demos = await screen.findByRole('region', { name: 'Recorded demo cases' })
    await user.click(await within(demos).findByRole('button', { name: /DEMO\/2026\/001/ }))
    await user.click(trace())
    await waitFor(() => expect(where()).toBe('/cases/demo-tron-okx'))
    expect(await screen.findByRole('heading', { level: 2, name: 'Why OKX?' })).toBeInTheDocument()
  })
})

describe('ways in', () => {
  it('the cases list leads to the sheet', async () => {
    const { user } = renderApp(<AppRoutes />, { route: '/cases' })
    await user.click(await screen.findByRole('link', { name: 'Open a case' }))
    expect(where()).toBe('/cases/new')
  })
})
