import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { CaseList, CaseSummary } from '../api/models'
import { readMock } from '../test/files'
import { Button } from './Button'
import { DataTable, type Column } from './DataTable'
import { Dialog } from './Dialog'
import { ToastProvider, useToast } from './Toast'

const cases = readMock<CaseList>('cases.json').items

const columns: Column<CaseSummary>[] = [
  { key: 'ref', header: 'Case', cell: (c) => c.case_ref, sortValue: (c) => c.case_ref ?? null },
  { key: 'chain', header: 'Chain', cell: (c) => c.chain, sortValue: (c) => c.chain },
  { key: 'confidence', header: 'Confidence', align: 'right', cell: (c) => c.confidence ?? 'none', sortValue: (c) => c.confidence ?? null },
  { key: 'address', header: 'Wallet', cell: (c) => c.address },
]

const firstColumn = () =>
  screen
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell')[0].textContent)

describe('DataTable', () => {
  const table = (extra: Partial<Parameters<typeof DataTable<CaseSummary>>[0]> = {}) => (
    <DataTable caption="Cases" columns={columns} rows={cases} rowKey={(c) => c.id} {...extra} />
  )

  it('has a caption, a header row and one row per record', () => {
    render(table())
    expect(screen.getByRole('table', { name: 'Cases' })).toBeInTheDocument()
    expect(screen.getAllByRole('columnheader')).toHaveLength(4)
    expect(screen.getAllByRole('row')).toHaveLength(cases.length + 1)
  })

  it('keeps the header in view while the body scrolls', () => {
    render(table())
    for (const th of screen.getAllByRole('columnheader')) expect(th).toHaveClass('sticky', 'top-0')
  })

  it('sorts by a column: ascending, then descending, and says so', async () => {
    const user = userEvent.setup()
    render(table())
    const header = screen.getByRole('columnheader', { name: /Case/ })
    expect(header).toHaveAttribute('aria-sort', 'none')

    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    expect(firstColumn()).toEqual(['DEMO/2026/001', 'DEMO/2026/002', 'DEMO/2026/003'])

    await user.click(within(header).getByRole('button'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    expect(firstColumn()).toEqual(['DEMO/2026/003', 'DEMO/2026/002', 'DEMO/2026/001'])
  })

  it('sorts numbers as numbers and puts rows with no value last, in either direction', async () => {
    const user = userEvent.setup()
    render(table())
    const header = screen.getByRole('columnheader', { name: /Confidence/ })
    const noValue = cases.find((c) => c.confidence == null)!.case_ref

    await user.click(within(header).getByRole('button'))
    expect(firstColumn().at(-1)).toBe(noValue)
    await user.click(within(header).getByRole('button'))
    expect(firstColumn().at(-1)).toBe(noValue)
    expect(firstColumn()[0]).toBe(cases.reduce((a, b) => ((a.confidence ?? 0) > (b.confidence ?? 0) ? a : b)).case_ref)
  })

  it('a column with no sort value has no sort button', () => {
    render(table())
    expect(within(screen.getByRole('columnheader', { name: 'Wallet' })).queryByRole('button')).not.toBeInTheDocument()
  })

  it('starts sorted when told to', () => {
    render(table({ initialSort: { key: 'ref', dir: 'desc' } }))
    expect(firstColumn()[0]).toBe('DEMO/2026/003')
    expect(screen.getByRole('columnheader', { name: /Case/ })).toHaveAttribute('aria-sort', 'descending')
  })

  it('opens a row with a click or with Enter', async () => {
    const user = userEvent.setup()
    const onRowOpen = vi.fn()
    render(table({ onRowOpen }))
    const row = screen.getAllByRole('row')[1]
    await user.click(row)
    expect(onRowOpen).toHaveBeenLastCalledWith(cases[0])
    row.focus()
    await user.keyboard('{Enter}')
    expect(onRowOpen).toHaveBeenCalledTimes(2)
  })

  it('does not open the row when a control inside it is used', async () => {
    const user = userEvent.setup()
    const onRowOpen = vi.fn()
    const withButton: Column<CaseSummary>[] = [{ key: 'copy', header: 'Copy', cell: () => <button type="button">Copy address</button> }]
    render(<DataTable caption="Cases" columns={withButton} rows={cases} rowKey={(c) => c.id} onRowOpen={onRowOpen} />)
    await user.click(screen.getAllByRole('button', { name: 'Copy address' })[0])
    expect(onRowOpen).not.toHaveBeenCalled()
  })

  it('shows skeleton rows while loading, and says so to screen readers', () => {
    const { container } = render(table({ rows: [], loading: true }))
    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThan(0)
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true')
  })

  it('shows the empty message when there are no rows', () => {
    render(table({ rows: [], empty: 'Paste a wallet address to open a case.' }))
    expect(screen.getByText('Paste a wallet address to open a case.')).toBeInTheDocument()
  })
})

describe('Toast', () => {
  function Trigger({ kind }: { kind?: 'info' | 'success' | 'error' }) {
    const toast = useToast()
    return <Button onClick={() => toast.show({ kind, title: 'Marked as sent', detail: 'Reply due 9 Oct 2026.' })}>Mark as sent</Button>
  }

  it('says what happened in a status region, in the words of the action', async () => {
    const user = userEvent.setup()
    render(<ToastProvider><Trigger kind="success" /></ToastProvider>)
    await user.click(screen.getByRole('button', { name: 'Mark as sent' }))
    const toast = screen.getByRole('status')
    expect(toast).toHaveTextContent('Marked as sent')
    expect(toast).toHaveTextContent('Reply due 9 Oct 2026.')
  })

  it('an error is an alert and stays until dismissed', async () => {
    vi.useFakeTimers()
    try {
      render(<ToastProvider><Trigger kind="error" /></ToastProvider>)
      fireEvent.click(screen.getByRole('button', { name: 'Mark as sent' }))
      expect(screen.getByRole('alert')).toBeInTheDocument()
      act(() => void vi.advanceTimersByTime(60_000))
      expect(screen.getByRole('alert')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('anything else leaves after six seconds', () => {
    vi.useFakeTimers()
    try {
      render(<ToastProvider><Trigger /></ToastProvider>)
      fireEvent.click(screen.getByRole('button', { name: 'Mark as sent' }))
      act(() => void vi.advanceTimersByTime(5900))
      expect(screen.getByRole('status')).toBeInTheDocument()
      act(() => void vi.advanceTimersByTime(200))
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('Dialog', () => {
  function Harness({ onClose = () => {} }: { onClose?: () => void }) {
    const [open, setOpen] = useState(false)
    return (
      <>
        <Button onClick={() => setOpen(true)}>Withdraw request</Button>
        <Dialog
          open={open}
          onClose={() => {
            setOpen(false)
            onClose()
          }}
          title="Withdraw this request?"
          footer={<Button variant="danger">Withdraw request</Button>}
        >
          Its wallets can be drafted again.
        </Dialog>
      </>
    )
  }

  it('opens as a modal named by its title', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Withdraw request' }))
    const dialog = screen.getByRole('dialog', { name: 'Withdraw this request?' })
    expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalled()
    expect(dialog).toHaveTextContent('Its wallets can be drafted again.')
    expect(within(dialog).getByRole('button', { name: 'Withdraw request' })).toBeInTheDocument()
  })

  it('closes from its close button, and when the browser closes it (Escape)', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<Harness onClose={onClose} />)

    await user.click(screen.getByRole('button', { name: 'Withdraw request' }))
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Withdraw request' }))
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
})
