import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { DestinationsByJurisdiction } from '../api/models'
import { FxFixed } from '../components/Rupees'
import { JurisdictionPanel } from './JurisdictionPanel'
import { PLACES } from './places'

const BASIS = 'Where the exchange is registered, not where the suspect is.'
// The two recorded Tron cases as the API answers them (tests/test_jurisdictions.py).
const DATA: DestinationsByJurisdiction = {
  basis: BASIS,
  places: [
    {
      jurisdiction: 'India',
      total_usd: 7530,
      wallets: 2,
      unpriced_wallets: 0,
      case_ids: ['tron-coindcx', 'tron-htx-coindcx'],
      exchanges: [
        {
          vasp: 'CoinDCX',
          total_usd: 7530,
          wallets: 2,
          unpriced_wallets: 0,
          case_ids: ['tron-coindcx', 'tron-htx-coindcx'],
          fiu_ind_registered: true,
          fiu_ind_as_of: '2024-12-02',
          source_urls: ['https://coindcx.s3.amazonaws.com/static/documents/terms-of-use.pdf'],
        },
      ],
    },
    {
      jurisdiction: 'Panama',
      total_usd: 7000,
      wallets: 1,
      unpriced_wallets: 0,
      case_ids: ['tron-htx-coindcx'],
      exchanges: [
        { vasp: 'HTX', total_usd: 7000, wallets: 1, unpriced_wallets: 0, case_ids: ['tron-htx-coindcx'], fiu_ind_registered: null, fiu_ind_as_of: null, source_urls: ['https://www.fca.org.uk/news/statements/htx-huobi-legal-proceedings'] },
      ],
    },
  ],
  not_on_record: [],
}

const show = (data: DestinationsByJurisdiction, scope: 'all' | 'case' = 'all') =>
  render(
    <MemoryRouter>
      <FxFixed rate={null}>
        <JurisdictionPanel data={data} scope={scope} />
      </FxFixed>
    </MemoryRouter>,
  )

describe('where the traced money went', () => {
  it('says what the map is and is not, and lists every exchange with its cited source', async () => {
    show(DATA)
    expect(screen.getByText(new RegExp(BASIS))).toBeInTheDocument()
    const table = screen.getByRole('table', { name: 'Traced money by the jurisdiction of the exchange it reached' })
    const india = within(table).getByRole('row', { name: /India/ })
    expect(india).toHaveTextContent('CoinDCX')
    expect(india).toHaveTextContent('Registered, as of 2 Dec 2024')
    expect(india).toHaveTextContent('$7,530')
    expect(within(india).getByRole('link', { name: 'coindcx.s3.amazonaws.com' })).toHaveAttribute('href', DATA.places[0].exchanges[0].source_urls![0])
    // no source for a registration is "No source", never "Not registered"
    expect(within(table).getByRole('row', { name: /HTX/ })).toHaveTextContent('No source')
    expect(within(table).getByRole('link', { name: 'HTX' })).toHaveAttribute('href', '/vasps/HTX')
  })

  it('draws a labelled dot per jurisdiction, and choosing one filters the table', async () => {
    show(DATA)
    const map = await screen.findByRole('group', { name: 'World map of the jurisdictions the traced money reached' })
    const dot = within(map).getByRole('button', { name: /^Panama: \$7,000, 1 case, HTX$/ })
    expect(within(map).getByRole('button', { name: /^India: \$7,530, 2 cases, CoinDCX$/ })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(dot)
    expect(dot).toHaveAttribute('aria-pressed', 'true')
    const table = screen.getByRole('table')
    expect(within(table).queryByText('CoinDCX')).not.toBeInTheDocument()
    expect(within(table).getByText('HTX')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show every jurisdiction' }))
    expect(within(table).getByText('CoinDCX')).toBeInTheDocument()
    // the dots answer to the keyboard too
    dot.focus()
    await userEvent.keyboard('{Enter}')
    expect(dot).toHaveAttribute('aria-pressed', 'true')
  })

  it('never places an exchange without a cited jurisdiction', () => {
    show({ basis: BASIS, places: [], not_on_record: [DATA.places[1].exchanges[0]] })
    expect(screen.getByLabelText('Jurisdiction not on record')).toHaveTextContent('HTX ($7,000)')
    expect(screen.getByLabelText('Jurisdiction not on record')).toHaveTextContent('No cited source gives a country for it, so none is shown.')
    expect(screen.queryByRole('group', { name: /World map/ })).not.toBeInTheDocument()
  })

  it('lists a jurisdiction it has no point for, and says it is not drawn', async () => {
    show({ ...DATA, places: [{ ...DATA.places[1], jurisdiction: 'Atlantis' }] })
    expect(screen.getByText(/Listed below but not drawn.*Atlantis/)).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Atlantis/ })).toHaveTextContent('HTX')
  })

  it('says so when there is nothing to place, for a case and for the dashboard', () => {
    const none = { basis: BASIS, places: [], not_on_record: [] }
    show(none, 'case').unmount()
    show(none, 'all')
    expect(screen.getByText('No finished case names an exchange yet.')).toBeInTheDocument()
  })

  it('has a point for every jurisdiction the directory cites today', () => {
    for (const name of ['India', 'Singapore', 'Hong Kong', 'Seychelles', 'British Virgin Islands', 'Cayman Islands', 'Panama']) expect(PLACES[name]).toBeDefined()
  })
})
