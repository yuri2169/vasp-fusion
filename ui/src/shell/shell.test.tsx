import { screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { CaseSummary } from '../api/models'
import { renderApp } from '../test/render'
import { GlobalSearch } from './GlobalSearch'

const DEMO_TRON = 'TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR' // mocks/cases/demo-tron-okx.json
const REAL_TRON = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' // real, but not in the fixtures
const REAL_ETH = '0x8971dd825ba5dd32b60307773f71f6e3efb0eda9'
const SOLANA = 'So11111111111111111111111111111111111111112'

afterEach(() => vi.restoreAllMocks())

const location = () => screen.getByTestId('location').textContent
const input = () => screen.getByRole('searchbox', { name: 'Wallet address' })
const traceButton = () => screen.getByRole('button', { name: 'Trace wallet' })

describe('GlobalSearch', () => {
  it('invites a wallet address, and cannot trace nothing', () => {
    renderApp(<GlobalSearch />)
    expect(input()).toHaveAttribute('placeholder', 'Paste a wallet address to open a case')
    expect(traceButton()).toBeDisabled()
  })

  it('guesses the chain while the officer is still typing', async () => {
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), 'TYJD2hZKBN')
    expect(screen.getByTitle('Looks like Tron')).toHaveTextContent('TRON')
    expect(traceButton()).toBeDisabled()
  })

  it('names the chain of a whole valid address and lets it be traced', async () => {
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), REAL_TRON)
    expect(screen.getByTitle('Tron')).toHaveTextContent('TRON')
    expect(traceButton()).toBeEnabled()
  })

  it('Enter opens the case and goes to it', async () => {
    const openCase = vi.spyOn(api, 'openCase')
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), `${DEMO_TRON}{Enter}`)
    await waitFor(() => expect(location()).toBe('/cases/demo-tron-okx'))
    expect(openCase).toHaveBeenCalledWith({ address: DEMO_TRON, chain: 'tron' }, undefined)
    expect(input()).toHaveValue('')
  })

  it('trims what was pasted', async () => {
    const openCase = vi.spyOn(api, 'openCase')
    const { user } = renderApp(<GlobalSearch />)
    await user.click(input())
    await user.paste(`  ${DEMO_TRON}\n`)
    await user.click(traceButton())
    await waitFor(() => expect(location()).toBe('/cases/demo-tron-okx'))
    expect(openCase).toHaveBeenCalledWith({ address: DEMO_TRON, chain: 'tron' }, undefined)
  })

  it('offers the EVM chains for an 0x address and sends the one picked', async () => {
    const openCase = vi.spyOn(api, 'openCase').mockResolvedValue({ id: 'c-0123456789' } as CaseSummary)
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), REAL_ETH)
    const picker = screen.getByRole('combobox', { name: 'Chain' })
    expect(within(picker).getAllByRole('option').map((o) => o.textContent)).toEqual(['Ethereum', 'Polygon', 'Arbitrum', 'Base', 'Optimism'])
    expect(picker).toHaveValue('ethereum')

    await user.selectOptions(picker, 'polygon')
    await user.click(traceButton())
    await waitFor(() => expect(location()).toBe('/cases/c-0123456789'))
    expect(openCase).toHaveBeenCalledWith({ address: REAL_ETH, chain: 'polygon' }, undefined)
  })

  it('catches a typo before any trace: says what is wrong, and Enter does nothing', async () => {
    const openCase = vi.spyOn(api, 'openCase')
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), `${REAL_TRON.replace('ZKBN', 'ZKBM')}{Enter}`)
    expect(screen.getByText(/checksum of this Tron address does not match/)).toBeInTheDocument()
    expect(input()).toHaveAttribute('aria-invalid', 'true')
    expect(traceButton()).toBeDisabled()
    expect(openCase).not.toHaveBeenCalled()
    expect(location()).toBe('/')
  })

  it('says a Solana wallet cannot be traced yet', async () => {
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), SOLANA)
    expect(screen.getByTitle('Solana')).toHaveTextContent('SOL')
    expect(screen.getByText(/Solana wallets cannot be traced yet/)).toBeInTheDocument()
    expect(traceButton()).toBeDisabled()
  })

  it("shows the server's sentence when the case cannot be opened", async () => {
    vi.spyOn(api, 'openCase').mockRejectedValue(new ApiError(503, 'The label database is missing. Run make labels, then try again.'))
    const { user } = renderApp(<GlobalSearch />)
    await user.type(input(), `${REAL_TRON}{Enter}`)
    expect(await screen.findByRole('alert')).toHaveTextContent('The label database is missing. Run make labels, then try again.')
    expect(input()).toHaveValue(REAL_TRON)
    expect(location()).toBe('/')
  })

  it('"/" puts the cursor in the search bar, Escape clears it', async () => {
    const { user } = renderApp(<GlobalSearch />)
    await user.keyboard('/')
    expect(input()).toHaveFocus()
    await user.keyboard('0x89')
    expect(input()).toHaveValue('0x89')
    await user.keyboard('{Escape}')
    expect(input()).toHaveValue('')
  })
})

describe('the app shell', () => {
  it('has the six places an investigator goes, and marks the current one', async () => {
    renderApp(<AppRoutes />, { route: '/desk' })
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    const names = within(nav).getAllByRole('link').map((a) => a.textContent)
    expect(names.slice(0, 6)).toEqual(['Cases', 'Request desk', 'Dashboard', 'Watchlist', 'Labels', 'Model'])
    expect(within(nav).getByRole('link', { name: 'Request desk' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Cases' })).not.toHaveAttribute('aria-current')
  })

  it('starts at the cases', async () => {
    renderApp(<AppRoutes />, { route: '/' })
    await waitFor(() => expect(location()).toBe('/cases'))
  })

  it('lets a keyboard user skip to the content', async () => {
    renderApp(<AppRoutes />, { route: '/cases' })
    const skip = await screen.findByRole('link', { name: 'Skip to content' })
    expect(skip).toHaveAttribute('href', '#content')
    expect(document.getElementById('content')).toBeInTheDocument()
  })

  it('shows who is signed in', async () => {
    renderApp(<AppRoutes />, { route: '/cases' })
    const me = await api.me()
    expect(await screen.findByText(me.officer!.name)).toBeInTheDocument()
    expect(screen.getByText(me.officer!.post!)).toBeInTheDocument()
  })

  it('says when the screen is showing demo data', async () => {
    renderApp(<AppRoutes />, { route: '/cases' })
    expect(await screen.findByText('Demo data')).toBeInTheDocument()
  })

  it('asks for a sign-in when the server requires one and nobody is signed in', async () => {
    vi.spyOn(api, 'me').mockResolvedValue({ auth_required: true, officer: null })
    renderApp(<AppRoutes />, { route: '/cases' })
    expect(await screen.findByRole('heading', { name: 'Sign in to VASP-FUSION' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main' })).not.toBeInTheDocument()
  })

  it('needs no sign-in when the server has no officer accounts', async () => {
    vi.spyOn(api, 'me').mockResolvedValue({ auth_required: false, officer: null })
    renderApp(<AppRoutes />, { route: '/cases' })
    expect(await screen.findByRole('navigation', { name: 'Main' })).toBeInTheDocument()
    expect(screen.getByText('No sign-in on this server')).toBeInTheDocument()
  })

  it('says so when the server cannot be reached, and offers to try again', async () => {
    vi.spyOn(api, 'me').mockRejectedValue(new ApiError(0, 'Cannot reach the VASP-FUSION server. Check that it is running, then try again.'))
    renderApp(<AppRoutes />, { route: '/cases' })
    const alert = await screen.findByRole('alert', {}, { timeout: 4000 })
    expect(alert).toHaveTextContent('Cannot reach the VASP-FUSION server')
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('an address that is not a page says so and points back to the cases', async () => {
    renderApp(<AppRoutes />, { route: '/nowhere' })
    expect(await screen.findByRole('heading', { name: 'There is no page here' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to cases' })).toHaveAttribute('href', '/cases')
  })
})

describe('sign-in', () => {
  it('signs in, then shows the app', async () => {
    const me = vi.spyOn(api, 'me').mockResolvedValue({ auth_required: true, officer: null })
    const login = vi.spyOn(api, 'login').mockImplementation(async () => {
      me.mockResolvedValue({ auth_required: true, officer: { username: 'a.rao', name: 'Insp. A. Rao', post: 'Cyber Crime PS' } })
      return { token: 't', token_type: 'bearer', expires_at: '2026-10-03T06:00:00Z', officer: { username: 'a.rao', name: 'Insp. A. Rao', post: 'Cyber Crime PS' } }
    })
    const { user } = renderApp(<AppRoutes />, { route: '/cases' })
    await user.type(await screen.findByLabelText('User name'), 'a.rao')
    await user.type(screen.getByLabelText('Password'), 'not-a-real-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(login).toHaveBeenCalledWith({ username: 'a.rao', password: 'not-a-real-password' })
    expect(await screen.findByText('Insp. A. Rao')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument()
  })

  it("shows the server's sentence when the sign-in is refused", async () => {
    vi.spyOn(api, 'me').mockResolvedValue({ auth_required: true, officer: null })
    vi.spyOn(api, 'login').mockRejectedValue(new ApiError(401, 'Wrong user name or password.'))
    const { user } = renderApp(<AppRoutes />, { route: '/cases' })
    await user.type(await screen.findByLabelText('User name'), 'a.rao')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong user name or password.')
  })
})

describe('cases', () => {
  it('lists the cases with their wallet, chain and outcome', async () => {
    renderApp(<AppRoutes />, { route: '/cases' })
    const table = await screen.findByRole('table', { name: 'Cases' })
    const list = await api.cases()
    await waitFor(() => expect(within(table).getAllByRole('row')).toHaveLength(list.items.length + 1))
    expect(within(table).getByText('DEMO/2026/001')).toBeInTheDocument()
    const stamps = within(table).getAllByTestId('outcome-stamp').map((s) => s.getAttribute('data-outcome'))
    expect(stamps.sort()).toEqual(['ATTRIBUTED', 'INSUFFICIENT_EVIDENCE', 'SANCTIONED_OR_MIXER_REACHED'])
  })

  it('opens a case from its row', async () => {
    const { user } = renderApp(<AppRoutes />, { route: '/cases' })
    await user.click(await screen.findByText('DEMO/2026/001'))
    await waitFor(() => expect(location()).toBe('/cases/demo-tron-okx'))
    expect(await screen.findByRole('list', { name: 'Path of the funds' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: 'Draft request to OKX' })).toBeInTheDocument()
  })

  it('an empty list invites the first case', async () => {
    vi.spyOn(api, 'cases').mockResolvedValue({ total: 0, items: [] })
    renderApp(<AppRoutes />, { route: '/cases' })
    expect(await screen.findByRole('heading', { name: 'No cases yet' })).toBeInTheDocument()
    expect(screen.getByText(/Open the first case with a wallet address/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open a case' })).toHaveAttribute('href', '/cases/new')
  })

  it('a case that does not exist says so', async () => {
    renderApp(<AppRoutes />, { route: '/cases/nope' })
    expect(await screen.findByRole('alert')).toHaveTextContent(/no demo fixture/i)
  })
})
