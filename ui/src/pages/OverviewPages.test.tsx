import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { Dashboard, LabelCoverage, ModelInfo, WalletDetail, WatchItem } from '../api/models'
import { renderApp } from '../test/render'

const open = (route: string) => renderApp(<AppRoutes />, { route })
const where = () => screen.getByTestId('location').textContent

/** What the live API answered on the eight real demo cases (4 Oct 2026), label counts shortened. */
const live: Dashboard = {
  counts: { cases_total: 8, open_cases: 4, wallets_attributed: 4, requests_awaiting_reply: 0, tracing: 0, failed: 0, awaiting_request: 3, watched: 3 },
  outcomes: { ATTRIBUTED: 4, INSUFFICIENT_EVIDENCE: 3, SANCTIONED_OR_MIXER_REACHED: 1 },
  top_vasps: [
    { vasp: 'Bitget', cases: 1, total_usd: 552163.8 },
    { vasp: 'CoinDCX', cases: 2, total_usd: 7530 },
    { vasp: 'HTX', cases: 2, total_usd: 7000 },
  ],
  chain_mix: [
    { chain: 'tron', cases: 4 },
    { chain: 'ethereum', cases: 3 },
    { chain: 'bitcoin', cases: 1 },
  ],
  median_time_to_attribution_s: 0,
  attribution_times_n: 4,
  recent_alerts: [
    {
      wallet: 'TFdHux43bs21qRsygv5WQWfgtbQeT6nXey',
      chain: 'tron',
      severity: 'high',
      at: '2026-10-03T03:58:48.476793Z',
      case_id: 'tron-ofac',
      text: 'Case DEMO/2026/103: 99% of the funds (100,008 USDT) reached a sanctioned address, TFdHux…T6nXey (OFAC SDN), 1 hop away',
    },
  ],
  label_coverage: {
    total: 457125,
    by_category: { exchange: 378616, entity: 62948 },
    by_tier: { curated: 338143, explorer_tag: 111795, derived: 5497, published_por: 1690 },
    by_chain: { bitcoin: 337192, ethereum: 88047, tron: 5895 },
    by_source: [], by_threat: {},
  },
}

describe('the dashboard', () => {
  it('counts what is on file, and every count leads to the list behind it (the demo fixture)', async () => {
    open('/dashboard')
    const counts = await screen.findByLabelText('Counts')
    const cell = (name: string) => within(counts).getByText(name).closest('a')!
    expect(cell('Cases')).toHaveTextContent('3')
    expect(cell('Cases')).toHaveAttribute('href', '/cases')
    expect(cell('Open cases')).toHaveAttribute('href', '/cases?open=1')
    expect(cell('Exchange named')).toHaveAttribute('href', '/cases?outcome=ATTRIBUTED')
    expect(cell('Exchanges to write to')).toHaveAttribute('href', '/desk')
    expect(cell('Awaiting a reply')).toHaveAttribute('href', '/requests?status=awaiting')
    expect(cell('Watched wallets')).toHaveAttribute('href', '/watchlist')
    // no case in the fixture has a measured time: the page says so and shows no figure
    expect(screen.getByText('Not yet measured: no finished case names an exchange.')).toBeInTheDocument()
  })

  it('the real demo cases: outcomes, exchanges, chains, the alert in the case’s own words', async () => {
    vi.spyOn(api, 'dashboard').mockResolvedValue(live)
    open('/dashboard')
    const outcomes = await screen.findByRole('list', { name: 'Finished cases by outcome' })
    expect(within(outcomes).getByRole('link', { name: /An exchange is named/ })).toHaveTextContent('450%')
    expect(within(outcomes).getByRole('link', { name: /Insufficient evidence/ })).toHaveAttribute('href', '/cases?outcome=INSUFFICIENT_EVIDENCE')
    expect(within(outcomes).getByRole('link', { name: /Sanctioned address or mixer/ })).toHaveAttribute('href', '/cases?outcome=SANCTIONED_OR_MIXER_REACHED')

    const exchanges = screen.getByRole('list', { name: 'Exchanges by traced US dollars' })
    const bitget = within(exchanges).getByRole('link', { name: /Bitget/ })
    expect(bitget).toHaveTextContent('$552,163.80')
    expect(bitget).toHaveTextContent('1 case')
    expect(bitget).toHaveAttribute('href', '/vasps/Bitget')

    const chains = screen.getByRole('list', { name: 'Cases by chain' })
    expect(within(chains).getAllByRole('link')[0]).toHaveAttribute('href', '/cases?chain=tron')

    expect(screen.getByText('same block')).toBeInTheDocument()
    expect(screen.getByText(/Median over the 4 cases that name an exchange/)).toBeInTheDocument()

    const alerts = screen.getByRole('region', { name: 'Alerts' })
    expect(within(alerts).getByText(live.recent_alerts[0].text)).toBeInTheDocument()
    expect(within(alerts).getByText('Alert')).toBeInTheDocument() // a word, not only a colour
    expect(within(alerts).getByRole('link', { name: 'Open the case' })).toHaveAttribute('href', '/cases/tron-ofac')

    const tiers = screen.getByRole('list', { name: 'Labels by tier' })
    expect(within(tiers).getByRole('link', { name: /Derived by VASP-FUSION/ })).toHaveAttribute('href', '/labels?tier=derived')
  })

  it('shows the server’s sentence when it cannot be loaded', async () => {
    vi.spyOn(api, 'dashboard').mockRejectedValue(new ApiError(422, 'The case store is locked. Try again in a moment.'))
    open('/dashboard')
    expect(await screen.findByText('The case store is locked. Try again in a moment.')).toBeInTheDocument()
  })
})

describe('the cases list, filtered from the dashboard', () => {
  it('shows only the cases of one outcome, says so, and the filter can be removed', async () => {
    const { user } = open('/cases?outcome=ATTRIBUTED')
    const filters = await screen.findByRole('group', { name: 'Filters' })
    await waitFor(() => expect(filters).toHaveTextContent('Showing 1 of 3:'))
    expect(within(screen.getByRole('table', { name: 'Cases' })).getAllByRole('row')).toHaveLength(2)
    await user.click(within(filters).getByRole('button', { name: 'Remove the filter: An exchange is named' }))
    await waitFor(() => expect(where()).toBe('/cases'))
    expect(within(screen.getByRole('table', { name: 'Cases' })).getAllByRole('row')).toHaveLength(4)
  })

  it('filters by chain, and ignores a filter it does not know', async () => {
    open('/cases?chain=ethereum&outcome=NONSENSE')
    const filters = await screen.findByRole('group', { name: 'Filters' })
    await waitFor(() => expect(filters).toHaveTextContent('Showing 1 of 3:'))
    expect(within(filters).getByRole('button')).toHaveTextContent('On Ethereum')
  })

  it('"open" is a case being traced or one whose exchange has not replied', async () => {
    open('/cases?open=1')
    const filters = await screen.findByRole('group', { name: 'Filters' })
    // the demo desk: OKX was asked and has not replied; CoinDCX has not been asked
    await waitFor(() => expect(filters).toHaveTextContent('Showing 2 of 3:'))
  })
})

describe('the labels explorer', () => {
  it('shows what the store covers, with the licence on record for each source and never a guess', async () => {
    open('/labels')
    const sources = await screen.findByRole('table', { name: 'Labels per source, with the licence on record' })
    const row = (name: RegExp) => within(sources).getByRole('link', { name }).closest('tr')!
    expect(row(/GraphSense TagPacks/)).toHaveTextContent('MIT')
    expect(row(/eth-labels/)).toHaveTextContent('Not recorded')
    expect(row(/OFAC SDN list of sanctioned addresses/)).toHaveTextContent('US-government public record')
    expect(screen.getByText(/"Not recorded" means this project holds no record of that source's own licence/)).toBeInTheDocument()
    // a count is a link to the labels behind it
    const tiers = screen.getByRole('list', { name: 'Labels by tier' })
    expect(within(tiers).getByRole('link', { name: /Curated list/ })).toHaveAttribute('href', '/labels?tier=curated')
    expect(screen.queryByRole('table', { name: 'Labels found' })).not.toBeInTheDocument()
  })

  it('searches by owner, keeps the search in the address, and links each address to its wallet page', async () => {
    const search = vi.spyOn(api, 'labelSearch')
    const { user } = open('/labels')
    await user.type(await screen.findByRole('searchbox', { name: 'Address or owner' }), 'coindcx')
    await user.click(screen.getByRole('button', { name: 'Search labels' }))
    await waitFor(() => expect(where()).toBe('/labels?q=coindcx'))
    const found = await screen.findByRole('table', { name: 'Labels found' })
    await waitFor(() => expect(within(found).getAllByRole('row').length).toBeGreaterThan(2))
    expect(search).toHaveBeenLastCalledWith({ q: 'coindcx', chain: '', category: '', tier: '', limit: 50, offset: 0 })
    expect(await screen.findByRole('heading', { name: '792 labels found' })).toBeInTheDocument()
    const owner = within(found).getAllByRole('link', { name: 'CoinDCX' })[0]
    expect(owner).toHaveAttribute('href', '/vasps/CoinDCX')
    expect(found).toHaveTextContent('Explorer tag')
    expect(found).toHaveTextContent('as its source') // a sourced label carries no confidence of its own
    // more than one page: the next one is asked for by offset
    await user.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(where()).toBe('/labels?q=coindcx&offset=50'))
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    await waitFor(() => expect(where()).toBe('/labels'))
  })

  it('a filter picked from the address is sent to the server', async () => {
    const search = vi.spyOn(api, 'labelSearch')
    open('/labels?chain=tron&tier=derived')
    await screen.findByRole('table', { name: 'Labels found' })
    expect(search).toHaveBeenCalledWith({ q: '', chain: 'tron', category: '', tier: 'derived', limit: 50, offset: 0 })
    expect(screen.getByRole('combobox', { name: 'Tier' })).toHaveValue('derived')
  })

  it('counts sources honestly when the coverage has unrecorded licences', async () => {
    const cov: LabelCoverage = {
      total: 10,
      by_category: { exchange: 10 },
      by_tier: { curated: 10 },
      by_chain: { tron: 10 },
      by_source: [{ source: 'x', name: 'A set nobody recorded', obtained_from: null, licence: null, url: null, labels: 10, tiers: { curated: 10 } }],
      by_threat: {},
    }
    vi.spyOn(api, 'labelCoverage').mockResolvedValue(cov)
    open('/labels')
    const sources = await screen.findByRole('table', { name: 'Labels per source, with the licence on record' })
    expect(within(sources).getAllByText('Not recorded')).toHaveLength(2) // where it came from, and its licence
  })
})

describe('the model page', () => {
  it('shows the measured figures, the rule they are read against, and every note as written', async () => {
    const model = await api.model('tron')
    open('/model')
    const measured = await screen.findByLabelText('Measured on the test addresses')
    expect(measured).toHaveTextContent('1,791')
    expect(measured).toHaveTextContent('over 0.999') // PR-AUC 1.0 is never printed as perfect
    expect(measured).not.toHaveTextContent('1.000')
    expect(measured).toHaveTextContent('98.6%')
    expect(screen.getByText(/That is the bar the model has to clear/)).toHaveTextContent('precision 0.934')
    expect(screen.getByText(/Its gain is on the look-alikes/)).toHaveTextContent('of the 97 test wallets')
    for (const note of model.notes) expect(screen.getByText(note)).toBeInTheDocument()

    expect(screen.getByRole('group', { name: /^Reliability plot/ })).toBeInTheDocument()
    expect(screen.getByRole('list', { name: 'Feature importance' })).toHaveTextContent('Share forwarded to one wallet22.8%')
    const folds = screen.getByRole('table', { name: 'Leave one exchange out' })
    expect(within(folds).getByText('CoinDCX').closest('tr')).toHaveTextContent('0.980')
    // the fixture holds no check of the naming bar: the page says so, with no figure
    expect(screen.getByText(/Not yet measured on Tron/)).toBeInTheDocument()
  })

  it('shows the check of the naming bar when the server has one', async () => {
    const model = await api.model('tron')
    const abstain: NonNullable<ModelInfo['abstain']> = {
      chain: 'tron',
      wallets: 280,
      claims: 303,
      current_threshold: 0.6,
      measured_threshold: null,
      target_risk: 0.05,
      delta: 0.05,
      bars: [{ threshold: 0.6, claims_answered: 159, claims_wrong: 17, wallets_named: 155, wallets_wrong: 15, wallets_abstained: 125, risk: 0.0968, risk_upper_bound: 0.173 }],
      risk_coverage: [
        { coverage: 0.5, accuracy: 0.9 },
        { coverage: 1, accuracy: 0.74 },
      ],
      notes: ['Validation set: 280 real Tron wallets.'],
    }
    vi.spyOn(api, 'model').mockResolvedValue({ ...model, abstain })
    open('/model')
    const panel = await screen.findByRole('region', { name: 'The 0.60 naming bar, checked' })
    expect(panel).toHaveTextContent('No bar brings the upper bound under 5%')
    const row = within(panel).getByText('in use').closest('tr')!
    expect(row).toHaveTextContent('155')
    expect(row).toHaveTextContent('9.7%')
    expect(row).toHaveTextContent('17.3%')
    expect(within(panel).getByText('Validation set: 280 real Tron wallets.')).toBeInTheDocument()
  })

  it('says "not yet measured" and shows no figure when the model has not been measured', async () => {
    const empty: ModelInfo = {
      status: 'not_measured',
      metrics: {},
      reliability: [],
      risk_coverage: [],
      feature_importance: [],
      leave_one_exchange_out: [],
      notes: ['No model has been measured yet: run `make model`.'],
    }
    const model = vi.spyOn(api, 'model').mockResolvedValue(empty)
    const { user } = open('/model')
    expect(await screen.findByRole('heading', { name: 'Not yet measured on Tron' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Measured on the test addresses')).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: /^Reliability plot/ })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Ethereum' }))
    await waitFor(() => expect(where()).toBe('/model?chain=ethereum'))
    expect(model).toHaveBeenLastCalledWith('ethereum')
    expect(await screen.findByRole('heading', { name: 'Not yet measured on Ethereum' })).toBeInTheDocument()
  })
})

describe('a wallet’s page', () => {
  const address = 'TFdHux43bs21qRsygv5WQWfgtbQeT6nXey'
  const sanctioned: WalletDetail = {
    address,
    chain: 'tron',
    labels: [
      {
        address,
        chain: 'tron',
        entity: 'OFAC SDN',
        category: 'sanctioned',
        kind: 'unknown',
        tier: 'curated',
        source: 'ofac-sdn',
        source_url: 'https://github.com/0xB10C/ofac-sanctioned-digital-currency-addresses',
        label: 'OFAC sanctioned (USDT)',
      },
    ],
    risk: {
      score: null,
      level: 'high',
      reasons: [
        'This address is on a sanctions list: OFAC sanctioned (USDT) (source: ofac-sdn).',
        'Case DEMO/2026/103: 99% of the funds (100,008 USDT) reached a sanctioned address, TFdHux…T6nXey (OFAC SDN), 1 hop away',
      ],
    },
    cases: [{ case_id: 'tron-ofac', role: 'sanctioned', hop: 1 }],
    inbound: {
      tx_count: 3,
      total_usd: 100008,
      total: 100008,
      asset: 'USDT',
      first_seen: '2024-11-25T02:47:27Z',
      last_seen: '2024-11-27T10:00:00Z',
      counterparties: 1,
      top_counterparties: ['TU1D9STZpxQjk3p4PXMjDVm1T6pYWpmwLV'],
    },
    outbound: null,
    flows_from_cases: 1,
    watched: false,
  }

  it('shows the label, what is on record against the address and why, its cases and the transfers they read', async () => {
    vi.spyOn(api, 'wallet').mockResolvedValue(sanctioned)
    open(`/wallets/tron/${address}`)
    const record = await screen.findByRole('region', { name: 'On record against this address' })
    expect(within(record).getByText('High')).toBeInTheDocument()
    for (const reason of sanctioned.risk.reasons) expect(within(record).getByText(reason)).toBeInTheDocument()
    expect(record).toHaveTextContent('No risk score is computed.')

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(address) // whole, never shortened
    expect(screen.getByRole('region', { name: 'Label' })).toHaveTextContent('OFAC SDN')
    const cases = screen.getByRole('table', { name: 'Cases this address appears in' })
    expect(within(cases).getByRole('link')).toHaveAttribute('href', `/cases/tron-ofac?wallet=${address}`)
    expect(cases).toHaveTextContent('Sanctioned address')

    const flows = screen.getByRole('region', { name: 'Transfers the cases read' })
    expect(flows).toHaveTextContent('Read from 1 stored case')
    expect(flows).toHaveTextContent('This is not the wallet\'s whole history.')
    expect(flows).toHaveTextContent('100,008 USDT')
    expect(flows).toHaveTextContent('25 Nov 2024 and 27 Nov 2024')
    expect(flows).toHaveTextContent('No case read a transfer out of this address.')
    expect(within(flows).getByRole('link', { name: /TU1D9S/ })).toHaveAttribute('href', '/wallets/tron/TU1D9STZpxQjk3p4PXMjDVm1T6pYWpmwLV')
  })

  it('an address nothing is known about is "not assessed", and can be traced or watched', async () => {
    const unknown = 'TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw'
    const { user } = open(`/wallets/tron/${unknown}`)
    const record = await screen.findByRole('region', { name: 'On record against this address' })
    expect(within(record).getByText('Not assessed')).toBeInTheDocument()
    expect(screen.getByText('No label. None of the label sources names the owner of this address.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trace this wallet' })).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Watch this wallet' }))
    expect(await screen.findByText('Watching this wallet')).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: 'Stop watching' }))
    expect(await screen.findByText('Stopped watching')).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: 'Watch this wallet' })).toBeInTheDocument()
  })

  it('refuses a chain it does not know', async () => {
    open('/wallets/dogecoin/D8abc')
    expect(await screen.findByRole('heading', { name: '"dogecoin" is not a chain this tool knows' })).toBeInTheDocument()
  })
})

describe('the watchlist', () => {
  const hero = 'TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR'

  it('invites a first wallet, catches a typo before anything is sent, and adds a wallet', async () => {
    const { user } = open('/watchlist')
    expect(await screen.findByRole('heading', { name: 'No wallet is being watched' })).toBeInTheDocument()
    const form = screen.getByRole('form', { name: 'Watch a wallet' })
    const input = within(form).getByRole('textbox', { name: 'Wallet address' })
    const add = within(form).getByRole('button', { name: 'Watch wallet' })
    expect(add).toBeDisabled()

    await user.type(input, `${hero.slice(0, -1)}S`)
    expect(within(form).getByText(/The checksum of this Tron address does not match/)).toBeInTheDocument()
    expect(add).toBeDisabled()

    await user.clear(input)
    await user.type(input, 'TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw')
    await user.type(within(form).getByRole('textbox', { name: 'Why it is watched (optional)' }), 'named in a complaint')
    await user.click(add)
    const list = await screen.findByRole('list', { name: 'Watched wallets' })
    expect(list).toHaveTextContent('Not traced yet')
    expect(list).toHaveTextContent('named in a complaint')
    expect(input).toHaveValue('')

    // demo data cannot trace: the refusal is the server's sentence
    await user.click(within(list).getByRole('button', { name: 'Check now' }))
    expect(await screen.findByText(/Demo data cannot trace a wallet again/)).toBeInTheDocument()

    await user.click(within(list).getByRole('button', { name: 'Stop watching' }))
    expect(await screen.findByRole('heading', { name: 'No wallet is being watched' })).toBeInTheDocument()
  })

  it('leads with a wallet that changed, says what is new in the server’s words, and marks it as seen', async () => {
    const base: WatchItem = {
      id: `tron-${hero}`,
      chain: 'tron',
      address: hero,
      note: null,
      added_at: '2026-10-01T10:00:00Z',
      added_by: 'a.rao',
      case_id: 'c-1',
      state: 'unchanged',
      last_checked_at: '2026-10-04T09:30:00Z',
      baseline_at: '2026-10-01T10:00:00Z',
      changes: [],
      error: null,
      label: null,
    }
    const changed: WatchItem = {
      ...base,
      id: 'tron-TU1D9STZpxQjk3p4PXMjDVm1T6pYWpmwLV',
      address: 'TU1D9STZpxQjk3p4PXMjDVm1T6pYWpmwLV',
      state: 'changed',
      changes: [
        { kind: 'new_alert', severity: 'high', at: '2026-10-04T09:30:00Z', text: 'New alert: 99% of the funds reached a sanctioned address' },
        { kind: 'new_exchange', severity: 'warn', at: '2026-10-04T09:30:00Z', text: 'New exchange contact: CoinDCX was reached, 1 hop away' },
        { kind: 'new_activity', severity: 'info', at: '2026-10-04T09:30:00Z', text: '2 new transfers of this wallet, the latest on 3 Oct 2026' },
      ],
    }
    const failed: WatchItem = { ...base, id: 'tron-x', address: 'TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw', state: 'failed', error: 'Refresh failed (CacheMiss: OFFLINE=1 and not cached).' }
    vi.spyOn(api, 'watchlist').mockResolvedValue({ items: [base, failed, changed] })
    const seen = vi.spyOn(api, 'markWatchSeen').mockResolvedValue({ ...changed, state: 'unchanged', changes: [] })
    const { user } = open('/watchlist')

    const rows = within(await screen.findByRole('list', { name: 'Watched wallets' })).getAllByRole('listitem').filter((li) => li.parentElement?.getAttribute('aria-label') === 'Watched wallets')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('Changed since last seen') // first, whatever its place in the answer
    const news = within(rows[0]).getByRole('list', { name: 'What is new' })
    for (const c of changed.changes) expect(within(news).getByText(c.text)).toBeInTheDocument()
    expect(rows[0]).toHaveTextContent('Compared with the trace of 1 Oct 2026, 10:00 UTC')
    expect(rows[0]).toHaveTextContent('by a.rao')
    expect(screen.getByText('3 wallets watched · 1 wallet changed')).toBeInTheDocument()
    expect(screen.getByText('Refresh failed (CacheMiss: OFFLINE=1 and not cached).')).toBeInTheDocument()
    // only a changed wallet can be marked as seen
    expect(screen.getAllByRole('button', { name: 'Mark as seen' })).toHaveLength(1)

    await user.click(within(rows[0]).getByRole('button', { name: 'Mark as seen' }))
    expect(seen).toHaveBeenCalledWith(changed.id)
    expect(await screen.findByText('Marked as seen')).toBeInTheDocument()
  })
})

describe('the rail', () => {
  it('has the watchlist, and keeps "Labels" lit on a wallet’s page', async () => {
    open('/wallets/tron/TGjpmhAFT6d7eBKvaFwPVN6H2pDKgLLZiw')
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: 'Watchlist' })).toHaveAttribute('href', '/watchlist')
    expect(within(nav).getByRole('link', { name: 'Labels' })).toHaveAttribute('aria-current', 'page')
    await screen.findByRole('region', { name: 'On record against this address' })
  })
})

describe('threat tags on the overview pages', () => {
  it('filters the labels explorer by threat and marks a tagged row', async () => {
    const search = vi.spyOn(api, 'labelSearch').mockResolvedValue({
      query: '',
      total: 1,
      limit: 50,
      offset: 0,
      items: [
        {
          address: 'TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ',
          chain: 'tron',
          entity: 'ISIL KHORASAN',
          category: 'sanctioned',
          kind: 'unknown',
          tier: 'curated',
          source: 'ofac-sdn-xml',
          threat: 'terrorism_financing',
          threat_entity: 'ISIL KHORASAN',
          threat_source: 'ofac-sdn-xml',
          threat_evidence: 'OFAC SDN list (published 2026-10-02), uid 18647: ISIL KHORASAN; programme FTO, SDGT. Listed as: TRX.',
        },
      ],
    })
    open('/labels?threat=terrorism_financing')
    const table = await screen.findByRole('table', { name: 'Labels found' })
    expect(search).toHaveBeenCalledWith({ q: '', chain: '', category: '', tier: '', threat: 'terrorism_financing', limit: 50, offset: 0 })
    expect(screen.getByRole('combobox', { name: 'Threat tag' })).toHaveValue('terrorism_financing')
    expect((await within(table).findByText('Terrorism financing')).closest('[data-threat]')).toHaveAttribute('data-threat', 'terrorism_financing')
  })
})
