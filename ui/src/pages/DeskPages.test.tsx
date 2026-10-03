import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { Desk, RequestDetail, RequestList, VaspDetail } from '../api/models'
import { pageRule } from '../desk/pageRule'
import { registrationWords } from '../desk/status'
import { readDesk } from '../test/files'
import { renderApp } from '../test/render'

// Answers of the real API on the real demo cases (src/test/fixtures/desk/README.md).
const deskBefore = readDesk<Desk>('desk-before')
const deskAfter = readDesk<Desk>('desk-after')
const coindcx = readDesk<VaspDetail>('vasp-CoinDCX-before')
const coindcxAfter = readDesk<VaspDetail>('vasp-CoinDCX-after')
const htx = readDesk<VaspDetail>('vasp-HTX')
const drafted = readDesk<RequestDetail>('request-drafted')
const approved = readDesk<RequestDetail>('request-approved')
const sent = readDesk<RequestDetail>('request-sent')
const htxDraft = readDesk<RequestDetail>('request-htx-drafted')
const register = readDesk<RequestList>('requests-after')

const open = (route: string) => renderApp(<AppRoutes />, { route })
const where = () => screen.getByTestId('location').textContent
const rowOf = (name: string) => screen.getByRole('link', { name }).closest('tr')!

describe('the request desk', () => {
  it('leads with what is overdue, then one row per exchange (the demo fixtures)', async () => {
    open('/desk')
    const followUp = await screen.findByRole('region', { name: 'Follow up' })
    expect(within(followUp).getByText('Reply overdue')).toBeInTheDocument()
    expect(within(followUp).getByText('OKX has not replied; the reply was due 21 Sep')).toBeInTheDocument()
    expect(within(followUp).getByRole('link', { name: 'Open request to OKX' })).toHaveAttribute('href', '/requests/demo-req-okx-001')
    const table = screen.getByRole('table', { name: 'Exchanges with traced wallets' })
    expect(within(table).getAllByRole('row')).toHaveLength(3)
    // the follow-up strip comes before the table
    expect(followUp.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('a real desk: wallets, the sum, the cases, the status and the next action in the server’s words', async () => {
    vi.spyOn(api, 'desk').mockResolvedValue(deskAfter)
    open('/desk')
    await screen.findByRole('link', { name: 'CoinDCX' })
    expect(screen.getByText('Nothing is overdue. No reply is past its day.')).toBeInTheDocument()

    const row = rowOf('CoinDCX')
    expect(row).toHaveTextContent('$7,530')
    expect(within(row).getByTestId('status-tag')).toHaveAttribute('data-status', 'sent')
    expect(row).toHaveTextContent('Await acknowledgement (reply due 10 Oct 2026)')
    expect(within(row).getByRole('link', { name: 'tron-coindcx' })).toHaveAttribute('href', '/cases/tron-coindcx')
    // every wallet is asked about: the request is offered, a new draft is not
    expect(within(row).getByRole('link', { name: 'Open request to CoinDCX' })).toHaveAttribute('href', '/requests/req-2026-0001')
    expect(within(row).queryByRole('button', { name: /Draft request/ })).not.toBeInTheDocument()

    // HTX has a draft and one wallet no request asks about: both are offered
    const other = rowOf('HTX')
    expect(other).toHaveTextContent('Draft a request for 1 wallet not yet requested')
    expect(within(other).getByRole('button', { name: 'Draft request to HTX' })).toBeInTheDocument()
    expect(within(other).getByRole('link', { name: 'Open request to HTX' })).toBeInTheDocument()
    // an exchange never asked
    expect(within(rowOf('Bitget')).getByTestId('status-tag')).toHaveAttribute('data-status', 'not_requested')
  })

  it('says how to get an exchange here when no case names one', async () => {
    vi.spyOn(api, 'desk').mockResolvedValue({ follow_ups: [], rows: [] })
    open('/desk')
    expect(await screen.findByRole('heading', { name: 'No exchange to write to yet' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open a case' })).toHaveAttribute('href', '/cases/new')
  })

  it('shows the server’s sentence when the desk cannot be loaded', async () => {
    vi.spyOn(api, 'desk').mockRejectedValue(new ApiError(503, 'The case store is locked. Try again in a moment.'))
    open('/desk')
    // a 5xx is asked for once more before it is shown
    expect(await screen.findByText('The case store is locked. Try again in a moment.', undefined, { timeout: 4000 })).toBeInTheDocument()
  })
})

describe('drafting a request', () => {
  const serve = () => {
    // a server with no sign-in: nobody's name to put under the signature line
    vi.spyOn(api, 'me').mockResolvedValue({ auth_required: false, officer: null })
    vi.spyOn(api, 'desk').mockResolvedValue(deskBefore)
    vi.spyOn(api, 'vasp').mockResolvedValue(coindcx)
    vi.spyOn(api, 'request').mockResolvedValue(drafted)
  }

  it('the link from a case opens the dialog with that case chosen; the letter opens as a draft', async () => {
    serve()
    const create = vi.spyOn(api, 'createRequest').mockResolvedValue(drafted)
    const { user } = open('/desk?vasp=CoinDCX&case=tron-coindcx')
    const dialog = await screen.findByRole('dialog', { name: 'Draft request to CoinDCX' })
    const boxes = await within(dialog).findAllByRole('checkbox')
    // two cases can be requested (the third wallet is context only); the one the link named is ticked
    expect(within(dialog).getByRole('checkbox', { name: /tron-coindcx/ })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: /tron-htx-coindcx/ })).not.toBeChecked()
    expect(within(dialog).queryByRole('checkbox', { name: /tron-abstain/ })).not.toBeInTheDocument()
    expect(boxes).toHaveLength(6)

    const draft = within(dialog).getByRole('button', { name: 'Draft request' })
    expect(draft).toBeDisabled() // no officer yet
    await user.click(within(dialog).getByRole('checkbox', { name: /tron-htx-coindcx/ }))
    await user.click(within(dialog).getByRole('checkbox', { name: /Preservation of records/ }))
    await user.type(within(dialog).getByLabelText('Investigating officer'), 'Insp. A. Rao, Cyber PS')
    await user.click(draft)

    expect(create).toHaveBeenCalledWith({
      vasp: 'CoinDCX',
      case_ids: ['tron-htx-coindcx', 'tron-coindcx'],
      asks: ['kyc', 'transactions', 'freeze'],
      officer: 'Insp. A. Rao, Cyber PS',
    })
    await waitFor(() => expect(where()).toBe('/requests/req-2026-0001'))
    expect(await screen.findByText('Request drafted')).toBeInTheDocument()
    expect(await screen.findByTestId('draft-banner')).toHaveTextContent('Draft - officer review required. Not sent.')
  })

  it('a row’s button opens it with every case chosen, and remembers the officer', async () => {
    serve()
    localStorage.setItem('vaspfusion.officer', 'SI R. Mehta, Cyber Cell')
    const { user } = open('/desk')
    await user.click(await screen.findByRole('button', { name: 'Draft request to CoinDCX' }))
    const dialog = await screen.findByRole('dialog', { name: 'Draft request to CoinDCX' })
    expect(await within(dialog).findByRole('checkbox', { name: /tron-coindcx/ })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: /tron-htx-coindcx/ })).toBeChecked()
    expect(within(dialog).getByLabelText('Investigating officer')).toHaveValue('SI R. Mehta, Cyber Cell')
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(where()).toBe('/desk')
  })

  it('a refusal stays in the dialog, in the server’s words', async () => {
    serve()
    const sentence = 'Every wallet of CoinDCX in these cases is already asked about in req-2026-0001.'
    vi.spyOn(api, 'createRequest').mockRejectedValue(new ApiError(409, sentence))
    localStorage.setItem('vaspfusion.officer', 'Insp. A. Rao')
    const { user } = open('/desk?vasp=CoinDCX')
    const dialog = await screen.findByRole('dialog')
    await within(dialog).findAllByRole('checkbox')
    await user.click(within(dialog).getByRole('button', { name: 'Draft request' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(sentence)
    expect(where()).toBe('/desk?vasp=CoinDCX')
  })
})

describe('an exchange’s page', () => {
  it('shows only cited facts, each with its source, and says a blank is a blank', async () => {
    vi.spyOn(api, 'vasp').mockResolvedValue(coindcxAfter)
    vi.spyOn(api, 'desk').mockResolvedValue(deskAfter)
    open('/vasps/CoinDCX')
    expect(await screen.findByRole('heading', { level: 1, name: 'CoinDCX' })).toBeInTheDocument()
    const facts = await screen.findByRole('region', { name: 'On file, with sources' })
    expect(facts).toHaveTextContent('Neblio Technologies Private Limited')
    expect(facts).toHaveTextContent('Registered, as of 4 Dec 2023')
    expect(within(facts).getAllByRole('link', { name: /Lok Sabha Unstarred Question No. 112/ })[0]).toHaveAttribute('href', expect.stringContaining('sansad.in'))
    // jurisdiction and channel: nothing cited
    expect(within(facts).getAllByText('No source found')).toHaveLength(2)
  })

  it('never reads a missing registration as "no"', async () => {
    vi.spyOn(api, 'vasp').mockResolvedValue(htx)
    open('/vasps/HTX')
    const facts = await screen.findByRole('region', { name: 'On file, with sources' })
    expect(facts).toHaveTextContent('A blank is not a "no"')
    expect(facts).toHaveTextContent('regulatory@htx-inc.com')
    expect(facts).toHaveTextContent('HTX asks for requests in English')
    expect(registrationWords({ fiu_ind_registered: null, fiu_ind_as_of: null })).toBe('No source found')
    expect(registrationWords({ fiu_ind_registered: false, fiu_ind_as_of: '2025-10-01' })).toBe('Named by FIU-IND as operating unregistered, as of 1 Oct 2025')
  })

  it('lists its wallets across cases, marks the ones no request can be drafted on, and its requests', async () => {
    vi.spyOn(api, 'vasp').mockResolvedValue(coindcxAfter)
    vi.spyOn(api, 'desk').mockResolvedValue(deskAfter)
    const { user } = open('/vasps/CoinDCX')
    const wallets = await screen.findByRole('table', { name: 'Wallets of CoinDCX in cases' })
    expect(within(wallets).getAllByRole('row')).toHaveLength(4)
    expect(within(wallets).getAllByText('Can be requested')).toHaveLength(2)
    expect(within(wallets).getAllByText('Context only')).toHaveLength(1)
    // every wallet is asked about already: the request is offered, not a second draft
    expect(screen.queryByRole('button', { name: 'Draft request to CoinDCX' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open request' })).toHaveAttribute('href', '/requests/req-2026-0001')

    const history = screen.getByRole('table', { name: 'Requests to CoinDCX' })
    vi.spyOn(api, 'request').mockResolvedValue(sent)
    await user.click(within(history).getByText('VF/REQ/2026/0001'))
    expect(where()).toBe('/requests/req-2026-0001')
  })

  it('offers the draft as the one primary action when a wallet is not asked about yet', async () => {
    vi.spyOn(api, 'vasp').mockResolvedValue(coindcx)
    vi.spyOn(api, 'desk').mockResolvedValue(deskBefore)
    const { user } = open('/vasps/CoinDCX')
    await user.click(await screen.findByRole('button', { name: 'Draft request to CoinDCX' }))
    expect(await screen.findByRole('dialog', { name: 'Draft request to CoinDCX' })).toBeInTheDocument()
    expect(where()).toBe('/vasps/CoinDCX?draft=1')
  })
})

describe('the request letter', () => {
  const serve = (r: RequestDetail) => vi.spyOn(api, 'request').mockResolvedValue(r)

  it('is the server’s letter, whole: addressee, subject, numbered paragraphs, wallets, asks, legal basis, signature', async () => {
    serve(drafted)
    open('/requests/req-2026-0001')
    const sheet = await screen.findByRole('article', { name: 'Request VF/REQ/2026/0001' })
    expect(sheet).toHaveTextContent('The Nodal Officer, Neblio Technologies Private Limited (CoinDCX)')
    expect(sheet).toHaveTextContent(drafted.letter.subject)
    const paragraphs = within(sheet).getAllByRole('listitem').filter((li) => li.closest('.sheet-paragraphs'))
    expect(paragraphs.map((li) => li.textContent)).toEqual(drafted.letter.paragraphs)
    // addresses and hashes whole, never shortened
    for (const w of drafted.letter.wallets) {
      expect(sheet).toHaveTextContent(w.address)
      for (const hash of w.tx_hashes ?? []) expect(sheet).toHaveTextContent(hash)
    }
    expect(sheet).toHaveTextContent('1,530 USDT')
    expect(sheet).toHaveTextContent('Derived by VASP-FUSION')
    expect(sheet).toHaveTextContent('Freeze: requested')
    expect(sheet).toHaveTextContent('Section 106 of the Bharatiya Nagarik Suraksha Sanhita, 2023')
    expect(sheet).toHaveTextContent('Section 63, Bharatiya Sakshya Adhiniyam, 2023: Admissibility of electronic records.')
    expect(sheet).toHaveTextContent('Seal of office')
    expect(sheet).toHaveTextContent('Investigating officer (unsigned draft)')
  })

  it('carries the watermark until it is approved, on screen and in the printed page’s margins', async () => {
    serve(drafted)
    const { unmount } = open('/requests/req-2026-0001')
    const sheet = await screen.findByRole('article')
    expect(sheet).toHaveAttribute('data-draft', 'true')
    expect(screen.getByTestId('draft-banner')).toBeInTheDocument()
    expect(pageRule(drafted.letter)).toContain('"DRAFT - OFFICER REVIEW REQUIRED. NOT SENT."')
    expect(pageRule(drafted.letter)).toContain('"VF/REQ/2026/0001  |  generated by VASP-FUSION from public blockchain records"')
    expect(pageRule(drafted.letter)).toContain('counter(page) " of " counter(pages)')
    unmount()

    serve(approved)
    open('/requests/req-2026-0001')
    expect(await screen.findByRole('article')).toHaveAttribute('data-draft', 'false')
    expect(screen.queryByTestId('draft-banner')).not.toBeInTheDocument()
    expect(screen.getByRole('article')).toHaveTextContent(/Investigating officer$|Investigating officerVF/)
    expect(pageRule(approved.letter)).not.toContain('NOT SENT')
  })

  it('a draft: what to check sits beside the letter, and approving is the one primary step', async () => {
    serve(htxDraft)
    const patch = vi.spyOn(api, 'patchRequest').mockResolvedValue({ ...htxDraft, status: 'approved', allowed_next: ['sent', 'drafted', 'withdrawn'] })
    const { user } = open('/requests/req-2026-0002')
    const notes = await screen.findByRole('region', { name: 'Check before approving' })
    expect(within(notes).getAllByRole('listitem').map((li) => li.textContent?.replace(/^–/, ''))).toEqual(htxDraft.letter.review_notes)
    expect(screen.getByRole('button', { name: 'Withdraw request' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Mark as sent/ })).not.toBeInTheDocument() // a draft cannot be sent

    await user.click(screen.getByRole('button', { name: 'Approve request' }))
    const dialog = screen.getByRole('dialog', { name: 'Approve the request to HTX?' })
    expect(dialog).toHaveTextContent('7 points are listed beside the letter to check first.')
    await user.type(within(dialog).getByRole('textbox'), 'Checked against the case file')
    await user.click(within(dialog).getByRole('button', { name: 'Approve request' }))
    expect(patch).toHaveBeenCalledWith('req-2026-0002', { status: 'approved', note: 'Checked against the case file' })
    expect(await screen.findByText('Request approved')).toBeInTheDocument()
    // the page now shows what the server answered
    expect(await screen.findByRole('button', { name: 'Mark as sent (via SAHYOG)' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Send back to draft' })).toBeInTheDocument()
  })

  it('approved: mark as sent, and the toast says so', async () => {
    serve(approved)
    const patch = vi.spyOn(api, 'patchRequest').mockResolvedValue(sent)
    const { user } = open('/requests/req-2026-0001')
    await user.click(await screen.findByRole('button', { name: 'Mark as sent (via SAHYOG)' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Mark as sent' }))
    expect(patch).toHaveBeenCalledWith('req-2026-0001', { status: 'sent', note: null })
    expect(await screen.findByText('Marked as sent')).toBeInTheDocument()
    const receipt = await screen.findByRole('region', { name: 'Gateway receipt' })
    expect(receipt).toHaveTextContent('outbox-3c1d75d9b03f')
    expect(receipt).toHaveTextContent(sent.receipt!.payload_sha256)
    expect(receipt).toHaveTextContent('nothing left this machine')
  })

  it('sent: the routing slip, the day a reply is due, and recording the reply', async () => {
    serve(sent)
    const patch = vi.spyOn(api, 'patchRequest').mockResolvedValue({ ...sent, status: 'answered', allowed_next: ['freeze_confirmed'] })
    const { user } = open('/requests/req-2026-0001')
    const slip = await screen.findByTestId('routing-slip')
    expect(within(slip).getAllByRole('listitem').map((li) => li.getAttribute('data-state'))).toEqual(['done', 'done', 'done', 'next', 'todo'])
    expect(slip).toHaveTextContent('Written to the SAHYOG outbox (mock-outbox); nothing left this machine')
    expect(screen.getByText(/reply due 10 Oct 2026/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Withdraw request' })).not.toBeInTheDocument() // too late to withdraw

    await user.click(screen.getByRole('button', { name: 'Record reply from CoinDCX' }))
    const dialog = screen.getByRole('dialog', { name: 'Record the reply from CoinDCX' })
    expect(within(dialog).getAllByRole('radio')).toHaveLength(4)
    await user.click(within(dialog).getByRole('radio', { name: /Answered/ }))
    await user.type(within(dialog).getByRole('textbox'), 'KYC of two accounts, by email')
    await user.click(within(dialog).getByRole('button', { name: 'Record reply' }))
    expect(patch).toHaveBeenCalledWith('req-2026-0001', { status: 'answered', note: 'KYC of two accounts, by email' })
    expect(await screen.findByText('Reply recorded')).toBeInTheDocument()
  })

  it('a step the server refuses is said in its words, and the dialog stays', async () => {
    serve(approved)
    const sentence = 'Case tron-coindcx was traced again and no longer supports this request. Withdraw this request and draft a new one.'
    vi.spyOn(api, 'patchRequest').mockRejectedValue(new ApiError(409, sentence))
    const { user } = open('/requests/req-2026-0001')
    await user.click(await screen.findByRole('button', { name: 'Mark as sent (via SAHYOG)' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Mark as sent' }))
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent(sentence)
  })

  it('prints through the browser', async () => {
    serve(sent)
    const print = vi.spyOn(window, 'print').mockImplementation(() => {})
    const { user } = open('/requests/req-2026-0001')
    await user.click(await screen.findByRole('button', { name: 'Print or save as PDF' }))
    expect(print).toHaveBeenCalledOnce()
  })

  it('the demo request works with no server: its reply can be recorded', async () => {
    const { user } = open('/requests/demo-req-okx-001')
    await user.click(await screen.findByRole('button', { name: 'Record reply from OKX' }))
    const dialog = screen.getByRole('dialog')
    await user.click(within(dialog).getByRole('radio', { name: /Refused/ }))
    await user.click(within(dialog).getByRole('button', { name: 'Record reply' }))
    expect(await screen.findByText('Reply recorded')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByTestId('status-tag')[0]).toHaveAttribute('data-status', 'refused'))
  })

  it('says so when there is no such request', async () => {
    vi.spyOn(api, 'request').mockRejectedValue(new ApiError(404, 'not found'))
    open('/requests/req-2026-0404')
    expect(await screen.findByText('There is no request "req-2026-0404".')).toBeInTheDocument()
  })
})

describe('the requests register', () => {
  const serve = () => {
    vi.spyOn(api, 'requests').mockResolvedValue(register)
    vi.spyOn(api, 'desk').mockResolvedValue(deskAfter)
  }
  const references = () =>
    within(screen.getByRole('table', { name: 'Requests' }))
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[0].textContent?.replace(/drafted.*/, ''))

  it('lists every request with its routing slip, newest first', async () => {
    serve()
    open('/requests')
    await screen.findByText('VF/REQ/2026/0001')
    expect(references()).toEqual(['VF/REQ/2026/0002', 'VF/REQ/2026/0001'])
    const slips = screen.getAllByTestId('routing-slip')
    expect(slips).toHaveLength(2)
    expect(within(slips[1]).getAllByRole('listitem').map((li) => li.getAttribute('data-state'))).toEqual(['done', 'done', 'done', 'next', 'todo'])
    expect(within(slips[1]).getAllByRole('listitem')[2]).toHaveAccessibleName(/^Sent on 3 Oct 2026, 04:07 UTC\. Written to the SAHYOG outbox/)
  })

  it('filters by status, exchange and text, and keeps the filter in the address', async () => {
    serve()
    const { user } = open('/requests')
    await screen.findByText('VF/REQ/2026/0001')
    const statuses = screen.getByRole('group', { name: 'Filter by status' })
    expect(within(statuses).getAllByRole('button').map((b) => b.textContent)).toEqual(['All2', 'Open2', 'Draft1', 'Sent1'])

    await user.click(within(statuses).getByRole('button', { name: /Sent/ }))
    expect(references()).toEqual(['VF/REQ/2026/0001'])
    expect(where()).toBe('/requests?status=sent')

    await user.click(within(statuses).getByRole('button', { name: /All/ }))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Exchange' }), 'HTX')
    expect(references()).toEqual(['VF/REQ/2026/0002'])
    expect(where()).toBe('/requests?vasp=HTX')

    await user.selectOptions(screen.getByRole('combobox', { name: 'Exchange' }), '')
    // by a wallet in the letter
    await user.type(screen.getByRole('searchbox', { name: 'Search the requests' }), 'TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5')
    expect(references()).toEqual(['VF/REQ/2026/0001'])
    await user.clear(screen.getByRole('searchbox', { name: 'Search the requests' }))
    await user.type(screen.getByRole('searchbox', { name: 'Search the requests' }), 'no such thing')
    expect(screen.getByText('No request matches these filters.')).toBeInTheDocument()
  })

  it('opens a filtered view from its address, and a row opens the letter', async () => {
    serve()
    vi.spyOn(api, 'request').mockResolvedValue(htxDraft)
    const { user } = open('/requests?status=drafted')
    await screen.findByText('VF/REQ/2026/0002')
    expect(references()).toEqual(['VF/REQ/2026/0002'])
    await user.click(screen.getByText('VF/REQ/2026/0002'))
    expect(where()).toBe('/requests/req-2026-0002')
  })

  it('invites a first request when there is none', async () => {
    vi.spyOn(api, 'requests').mockResolvedValue({ items: [] })
    open('/requests')
    expect(await screen.findByRole('heading', { name: 'No request has been drafted' })).toBeInTheDocument()
  })
})

describe('the desk in the shell', () => {
  it('keeps the rail on "Request desk" on an exchange’s page and on a request', async () => {
    open('/requests/demo-req-okx-001')
    await screen.findByRole('article')
    expect(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Request desk' })).toHaveAttribute('aria-current', 'page')
  })

  it('the two views of the desk link to each other with their counts', async () => {
    open('/desk')
    const views = await screen.findByRole('navigation', { name: 'Request desk views' })
    await waitFor(() => expect(within(views).getByRole('link', { name: /All requests/ })).toHaveTextContent('All requests1'))
    expect(within(views).getByRole('link', { name: /By exchange/ })).toHaveAttribute('aria-current', 'page')
  })
})
