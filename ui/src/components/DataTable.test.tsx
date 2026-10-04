import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataTable, type Column } from './DataTable'

type Row = { id: number }
const columns: Column<Row>[] = [{ key: 'id', header: 'Number', cell: (r) => `row ${r.id}`, sortValue: (r) => r.id }]
const rows = (n: number): Row[] => Array.from({ length: n }, (_, i) => ({ id: i + 1 }))
const bodyRows = () => screen.getAllByRole('row').length - 1

describe('DataTable with many rows', () => {
  it('renders a short table whole, with nothing under it', () => {
    render(<DataTable caption="Short" columns={columns} rows={rows(40)} rowKey={(r) => String(r.id)} />)
    expect(bodyRows()).toBe(40)
    expect(screen.queryByRole('button', { name: /^Show/ })).not.toBeInTheDocument()
  })

  it('renders the first 200 of a long one, says how many are left, and shows more on request', async () => {
    render(<DataTable caption="Long" columns={columns} rows={rows(2000)} rowKey={(r) => String(r.id)} />)
    expect(bodyRows()).toBe(200)
    expect(screen.getByText('Showing 200 of 2,000')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show 200 more' }))
    expect(bodyRows()).toBe(400)
    await userEvent.click(screen.getByRole('button', { name: 'Show all 2,000' }))
    expect(bodyRows()).toBe(2000)
    expect(screen.queryByRole('button', { name: /^Show/ })).not.toBeInTheDocument()
  })

  it('sorts all the rows, not only the ones on screen', async () => {
    render(<DataTable caption="Long" columns={columns} rows={rows(2000)} rowKey={(r) => String(r.id)} initialSort={{ key: 'id', dir: 'asc' }} />)
    await userEvent.click(screen.getByRole('button', { name: 'Number' }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('row 2000')
  })
})
