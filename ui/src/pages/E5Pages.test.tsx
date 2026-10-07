import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { CaseDetail, Desk, LetterOfRequest, RequestDetail } from '../api/models'
import { daysLeft, daysLeftWords, elapsedWords } from '../desk/status'
import { readDesk, readE5 } from '../test/files'
import { renderApp } from '../test/render'

// Answers of the real API on the real two-exchange demo case (src/test/fixtures/e5/record.py).
const before = readE5<CaseDetail>('case-before')
const after = readE5<CaseDetail>('case-after')
const desk = readE5<Desk>('desk-after')
const letter = readE5<LetterOfRequest>('letter-of-request-HTX')
const approved = readDesk<RequestDetail>('request-approved')

const open = (route: string) => renderApp(<AppRoutes />, { route })

describe('the case events tab', () => {
  it('lists what was recorded with its time and record, and what is pending without a time', async () => {
    vi.spyOn(api, 'case').mockResolvedValue(after)
    open(`/cases/${after.id}?tab=events`)
    const events = await screen.findByRole('region', { name: 'Case events' })
    expect(within(events).getByText(after.timeline!.note)).toBeInTheDocument()
    const items = within(events).getAllByRole('listitem')
    expect(items).toHaveLength(after.timeline!.steps.length)

    const named = items.find((li) => li.textContent?.includes('Exchange named: CoinDCX, HTX'))!
    expect(named).toHaveAttribute('data-state', 'done')
    expect(within(named).getByText(/UTC$/)).toHaveAttribute('datetime', after.timeline!.steps.find((s) => s.key === 'exchange_named')!.at)
    expect(named).toHaveTextContent('from the case store')

    const sent = items.find((li) => li.textContent?.includes('Request to CoinDCX sent'))!
    expect(within(sent).getByRole('link')).toHaveAttribute('href', '/requests/req-2026-0001')

    const pending = items.filter((li) => li.getAttribute('data-state') === 'pending')
    expect(pending.map((li) => li.querySelector('time'))).toEqual(pending.map(() => null))
    expect(pending.at(-1)).toHaveTextContent('Request to HTX: not drafted')
    expect(pending.at(-1)).toHaveTextContent('Pending')
    // the draft for the foreign authority is an event, and says it was not sent
    expect(events).toHaveTextContent('Letter-of-request draft for HTX made')
    expect(events).toHaveTextContent('Not sent by this tool.')
  })

  it('counts only recorded steps on the tab', async () => {
    vi.spyOn(api, 'case').mockResolvedValue(before)
    open(`/cases/${before.id}`)
    const done = before.timeline!.steps.filter((s) => s.state === 'done').length
    expect(await screen.findByRole('tab', { name: `Case events ${done}` })).toBeInTheDocument()
  })

  it('says so when a case has no events to read', async () => {
    vi.spyOn(api, 'case').mockResolvedValue({ ...before, timeline: null })
    open(`/cases/${before.id}?tab=events`)
    expect(await screen.findByRole('heading', { name: 'No case events to show' })).toBeInTheDocument()
  })

  it('words elapsed time the way the server does', () => {
    expect([0.4, 14, 150, 3 * 3600 + 120, 2 * 86400 + 3600].map(elapsedWords)).toEqual(['under 1 s', '14 s', '2 min 30 s', '3 h 2 min', '2 d 1 h'])
  })
})

describe('who to write to first', () => {
  it('orders the two exchanges on the case page with the server’s reasons and the right actions', async () => {
    vi.spyOn(api, 'case').mockResolvedValue(before)
    open(`/cases/${before.id}`)
    const panel = await screen.findByRole('region', { name: 'Who to write to first' })
    const order = before.write_order!
    expect(panel).toHaveTextContent(order.rule)
    expect(panel).toHaveTextContent('No response time is stated')
    const rows = within(panel).getAllByRole('listitem').filter((li) => li.parentElement?.tagName === 'OL')
    expect(rows.map((li) => within(li).getAllByRole('link')[0].textContent)).toEqual(['CoinDCX', 'HTX'])
    for (const [i, x] of order.exchanges.entries()) for (const reason of x.reasons) expect(rows[i]).toHaveTextContent(reason)
    expect(within(rows[0]).getByRole('link', { name: 'Draft request to CoinDCX' })).toHaveAttribute('href', `/desk?vasp=CoinDCX&case=${before.id}`)
    expect(within(rows[0]).queryByRole('link', { name: /Letter-of-request/ })).toBeNull()
    expect(within(rows[1]).getByRole('link', { name: 'Letter-of-request draft for HTX' })).toHaveAttribute(
      'href',
      `/vasps/HTX/letter-of-request?case=${before.id}`,
    )
  })

  it('shows the open request instead of a draft button once one is sent', async () => {
    vi.spyOn(api, 'case').mockResolvedValue(after)
    open(`/cases/${after.id}`)
    const panel = await screen.findByRole('region', { name: 'Who to write to first' })
    expect(within(panel).getByRole('link', { name: 'Open request to CoinDCX' })).toHaveAttribute('href', '/requests/req-2026-0001')
    expect(within(panel).getByTestId('status-tag')).toHaveAttribute('data-status', 'sent')
  })

  it('is on the desk for the case that reaches two exchanges, with the reply still awaited above it', async () => {
    vi.spyOn(api, 'desk').mockResolvedValue(desk)
    open('/desk')
    const followUp = await screen.findByRole('region', { name: 'Follow up' })
    const due = desk.follow_ups[0]
    expect(within(followUp).getByText('Reply awaited')).toBeInTheDocument()
    expect(within(followUp).getByText(due.text)).toBeInTheDocument()
    expect(followUp).toHaveTextContent(daysLeftWords(daysLeft(due.due)))
    const first = screen.getByRole('region', { name: 'Who to write to first' })
    expect(within(first).getByRole('link', { name: desk.write_first[0].case_ref! })).toHaveAttribute('href', `/cases/${desk.write_first[0].case_id}`)
    expect(within(first).getByRole('link', { name: 'Letter-of-request draft for HTX' })).toBeInTheDocument()
    // a row offers the draft only where no source shows a registration
    expect(screen.getByRole('link', { name: 'Letter-of-request draft for Bitget' })).toHaveAttribute('href', '/vasps/Bitget/letter-of-request')
    expect(screen.queryByRole('link', { name: 'Letter-of-request draft for CoinDCX' })).toBeNull()
  })

  it('counts the days to a reply in UTC days', () => {
    const today = new Date('2026-10-08T03:00:00Z')
    expect(['2026-10-18', '2026-10-08', '2026-10-05'].map((d) => daysLeftWords(daysLeft(d, today)))).toEqual(['10 days left', 'due today', '3 days overdue'])
    expect(daysLeftWords(1)).toBe('1 day left')
  })
})

describe('the letter-of-request draft', () => {
  it('asks for the officer first, then draws the draft with its mark, its blanks and its checks', async () => {
    const made = vi.spyOn(api, 'letterOfRequest').mockResolvedValue(letter)
    vi.spyOn(api, 'me').mockResolvedValue({ auth_required: false, officer: null })
    localStorage.clear()
    open('/vasps/HTX/letter-of-request?case=tron-htx-coindcx')
    const name = await screen.findByLabelText('Investigating officer')
    expect(made).not.toHaveBeenCalled()
    await userEvent.type(name, 'Insp. A. Rao, Cyber PS')
    await userEvent.click(screen.getByRole('button', { name: 'Make draft' }))
    await waitFor(() => expect(made).toHaveBeenCalledWith('HTX', 'Insp. A. Rao, Cyber PS', ['tron-htx-coindcx']))

    const sheet = await screen.findByRole('article', { name: 'Letter-of-request draft' })
    expect(within(sheet).getByTestId('draft-banner')).toHaveTextContent('Draft: officer and competent authority review required. Not sent.')
    expect(sheet).toHaveTextContent('The competent Court or authority, ____________________')
    expect(sheet).toHaveTextContent('Section 112, Bharatiya Nagarik Suraksha Sanhita, 2023')
    expect(within(sheet).getByLabelText('left blank for the Court')).toBeInTheDocument()
    for (const w of letter.letter.wallets) expect(sheet).toHaveTextContent(w.address)
    expect(sheet).toHaveTextContent('Applicant. The letter is issued by the Court, not by this office.')

    expect(screen.getByRole('region', { name: 'Standing' })).toHaveTextContent('Draft. Not sent, and not a request of this desk')
    const checks = screen.getByRole('region', { name: 'Check before use' })
    expect(within(checks).getAllByRole('listitem')).toHaveLength(letter.letter.review_notes!.length)
    expect(checks).toHaveTextContent('No jurisdiction is on record for HTX.')
    expect(screen.getByRole('link', { name: 'Open draft PDF' })).toHaveAttribute('href', letter.pdf_url)
  })

  it('shows the server’s sentence where the domestic notice applies', async () => {
    localStorage.setItem('vaspfusion.officer', 'Insp. A. Rao')
    vi.spyOn(api, 'letterOfRequest').mockRejectedValue(
      new ApiError(422, 'CoinDCX is registered with FIU-IND as of 2023-12-04 (as cited in the directory): the domestic notice applies. Draft a request instead.'),
    )
    open('/vasps/CoinDCX/letter-of-request')
    expect(await screen.findByText(/the domestic notice applies/)).toBeInTheDocument()
    localStorage.clear()
  })
})

describe('the reply day', () => {
  it('is sent with "mark as sent" when the officer gives one, and left out otherwise', async () => {
    vi.spyOn(api, 'request').mockResolvedValue(approved)
    const patch = vi.spyOn(api, 'patchRequest').mockResolvedValue(approved)
    open(`/requests/${approved.id}`)
    await userEvent.click(await screen.findByRole('button', { name: 'Mark as sent' }))
    const dialog = screen.getByRole('dialog')
    const day = within(dialog).getByLabelText('Reply due (optional)')
    expect(dialog).toHaveTextContent('Neither is a period set by law.')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Mark as sent' }))
    await waitFor(() => expect(patch).toHaveBeenLastCalledWith(approved.id, { status: 'sent', note: null }))

    await userEvent.click(await screen.findByRole('button', { name: 'Mark as sent' }))
    const again = screen.getByRole('dialog')
    await userEvent.type(within(again).getByLabelText('Reply due (optional)'), '2031-01-15')
    await userEvent.click(within(again).getByRole('button', { name: 'Mark as sent' }))
    await waitFor(() => expect(patch).toHaveBeenLastCalledWith(approved.id, { status: 'sent', note: null, due: '2031-01-15' }))
    expect(day).toBeDefined()
  })
})
