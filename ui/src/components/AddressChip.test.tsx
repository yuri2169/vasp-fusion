import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router'
import { AddressChip } from './AddressChip'
import { TxHash } from './TxHash'

const SUSPECT = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' // the hero demo wallet (demo/cases.json)
const OKX = 'THS5KLm2HwoZyXt5XeVpfuhdKkXpotELsR' // a real OKX proof-of-reserves wallet (mocks/)
const HASH = 'c09b2c24e2a4a6fd4308788cb7b6e9a9c340275ac162c4281ed549100c07287b'

describe('AddressChip', () => {
  it('shows the middle-truncated address in mono', () => {
    render(<AddressChip address={OKX} chain="tron" />)
    const short = screen.getByText('THS5KL…otELsR')
    expect(short).toHaveClass('font-mono')
  })

  it('names the whole address for screen readers', () => {
    render(<AddressChip address={OKX} chain="tron" />)
    expect(screen.getByRole('group', { name: `Tron address ${OKX}` })).toBeInTheDocument()
  })

  it('shows the whole address on hover, and on keyboard focus', async () => {
    const user = userEvent.setup()
    render(<AddressChip address={OKX} chain="tron" />)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    await user.hover(screen.getByText('THS5KL…otELsR'))
    expect(screen.getByRole('tooltip')).toHaveTextContent(OKX)
    await user.unhover(screen.getByText('THS5KL…otELsR'))
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    await user.tab()
    expect(screen.getByRole('tooltip')).toHaveTextContent(OKX)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('copies the whole address, never the short form', async () => {
    const user = userEvent.setup()
    render(<AddressChip address={OKX} chain="tron" />)
    await user.click(screen.getByRole('button', { name: 'Copy address' }))
    expect(await navigator.clipboard.readText()).toBe(OKX)
  })

  it('links to the block explorer in a new tab', () => {
    render(<AddressChip address={OKX} chain="tron" />)
    const link = screen.getByRole('link', { name: 'Open on tronscan.org (new tab)' })
    expect(link).toHaveAttribute('href', `https://tronscan.org/#/address/${OKX}`)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('prints the address whole when asked (letters, tables of record)', () => {
    render(<AddressChip address={OKX} chain="tron" full />)
    expect(screen.getByText(OKX)).toBeInTheDocument()
  })

  it('names the owner and the tier of a labelled address, in words as well as by icon', async () => {
    const user = userEvent.setup()
    const { container } = render(<AddressChip address={OKX} chain="tron" entity="OKX" tier="published_por" />)
    expect(screen.getByText('OKX')).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
    expect(screen.getByRole('group')).toHaveAccessibleName(`Tron address ${OKX}, OKX, Published by exchange`)
    await user.hover(screen.getByText('THS5KL…otELsR'))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Published by exchange')
  })

  it('marks the suspect wallet', () => {
    render(<AddressChip address={SUSPECT} chain="tron" role="suspect" />)
    expect(screen.getByText('Suspect')).toBeInTheDocument()
  })

  it('links the address to its page when given one', () => {
    render(
      <MemoryRouter>
        <AddressChip address={OKX} chain="tron" to={`/wallets/tron/${OKX}`} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'THS5KL…otELsR' })).toHaveAttribute('href', `/wallets/tron/${OKX}`)
  })
})

describe('TxHash', () => {
  it('shows the short hash, copies the whole one, and links to the explorer', async () => {
    const user = userEvent.setup()
    render(<TxHash hash={HASH} chain="tron" />)
    expect(screen.getByText('c09b2c…07287b')).toHaveClass('font-mono')
    await user.click(screen.getByRole('button', { name: 'Copy transaction hash' }))
    expect(await navigator.clipboard.readText()).toBe(HASH)
    expect(screen.getByRole('link', { name: 'Open on tronscan.org (new tab)' })).toHaveAttribute(
      'href',
      `https://tronscan.org/#/transaction/${HASH}`,
    )
  })

  it('shows the whole hash on hover', async () => {
    const user = userEvent.setup()
    render(<TxHash hash={HASH} chain="tron" />)
    await user.hover(screen.getByText('c09b2c…07287b'))
    expect(screen.getByRole('tooltip')).toHaveTextContent(HASH)
  })

  it('prints the hash whole when asked', () => {
    render(<TxHash hash={HASH} chain="tron" full />)
    expect(screen.getByText(HASH)).toBeInTheDocument()
  })
})
