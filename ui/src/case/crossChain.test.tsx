import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { AddressChip } from '../components/AddressChip'
import { BridgeLeg } from '../components/BridgeLeg'
import { HopRail } from '../components/HopRail'
import { TxHash } from '../components/TxHash'
import { buildFlow, mainPath } from '../lib/caseGraph'
import { splitWalletId, walletId } from '../lib/chains'
import { fundsName } from '../lib/funds'
import { timelineOf } from '../lib/timeline'
import { TxChains } from '../lib/txChains'
import { readCase } from '../test/files'
import { tileLabel, toElements } from './flowStyle'
import { TransfersTab } from './tabs/TransfersTab'

/** The real recorded wallet whose money crossed from Ethereum to Base over Across (G4). */
const c = readCase<CaseDetail>('eth-bridge')
const me = c.address
const across = '0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5'
const big = c.crossings!.find((x) => x.amount_in === 7800)!
const stamp = { outcome: c.outcome!, vasp: c.top_vasp, confidence: c.confidence }

describe('wallet ids', () => {
  it('a wallet on the case’s chain is its address; on another chain it carries the chain', () => {
    expect(walletId('ethereum', me, 'ethereum')).toBe(me)
    expect(walletId('ethereum', me, null)).toBe(me)
    expect(walletId('ethereum', me, 'base')).toBe(`base:${me}`)
    expect(splitWalletId(`base:${me}`, 'ethereum')).toEqual({ chain: 'base', address: me, away: true })
    expect(splitWalletId(me, 'ethereum')).toEqual({ chain: 'ethereum', address: me, away: false })
  })

  it('the same address is two wallets in the case: the suspect, and the recipient on Base', () => {
    const ids = c.graph.nodes.map((n) => n.id)
    expect(ids).toContain(me)
    expect(ids).toContain(`base:${me}`)
    expect(c.graph.nodes.find((n) => n.id === `base:${me}`)).toMatchObject({ address: me, chain: 'base', hop: 2 })
  })
})

describe('an address chip for a wallet on another chain', () => {
  it('shows the chain’s code and the plain address, and links to that chain’s explorer', () => {
    render(<AddressChip address={`base:${me}`} chain="ethereum" />)
    expect(screen.getByTestId('chip-chain')).toHaveTextContent('BASE')
    expect(screen.getByRole('group', { name: `Base address ${me}` })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /basescan\.org/ })).toHaveAttribute('href', `https://basescan.org/address/${me}`)
    expect(screen.queryByText(/base:/)).not.toBeInTheDocument()
  })

  it('a wallet on the case’s own chain has no chain mark', () => {
    render(<AddressChip address={me} chain="ethereum" />)
    expect(screen.queryByTestId('chip-chain')).not.toBeInTheDocument()
  })
})

describe('a transaction link', () => {
  it('opens the chain the case says the transaction is on', () => {
    render(
      <TxChains.Provider value={c.tx_chains!}>
        <TxHash hash={big.payout_tx!} chain="ethereum" />
        <TxHash hash={big.source_tx} chain="ethereum" />
      </TxChains.Provider>,
    )
    const [payout, deposit] = screen.getAllByRole('link')
    expect(payout).toHaveAttribute('href', `https://basescan.org/tx/${big.payout_tx}`)
    expect(deposit).toHaveAttribute('href', `https://etherscan.io/tx/${big.source_tx}`)
  })
})

describe('the Hop Rail across a bridge', () => {
  const rail = () => render(<HopRail suspect={{ address: me, chain: c.chain }} hops={c.hop_rail} stamp={stamp} />)

  it('draws the crossing apart from an ordinary hop: the bridge, both chains, what arrived', () => {
    rail()
    expect(screen.getAllByTestId('hop-stub')).toHaveLength(2)
    const ticket = screen.getByTestId('hop-bridge')
    expect(ticket).toHaveTextContent('Across Protocol')
    expect(ticket).toHaveTextContent('ETH')
    expect(ticket).toHaveTextContent('BASE')
    expect(ticket).toHaveTextContent('7,777.39')
    expect(ticket).toHaveTextContent('54 s later')
    expect(ticket).toHaveAccessibleName(/crossed from Ethereum to Base over the Across Protocol bridge/)
  })

  it('links both transactions, each on its own chain’s explorer', () => {
    rail()
    const ticket = within(screen.getByTestId('hop-bridge'))
    expect(ticket.getByRole('link', { name: /deposit on etherscan\.io/ })).toHaveAttribute('href', `https://etherscan.io/tx/${big.source_tx}`)
    expect(ticket.getByRole('link', { name: /payout on basescan\.org/ })).toHaveAttribute('href', `https://basescan.org/tx/${big.payout_tx}`)
  })

  it('the hop after the crossing is on Base: its wallet is marked and its stub opens Basescan', () => {
    rail()
    const steps = within(screen.getByRole('list', { name: 'Path of the funds' })).getAllByRole('listitem')
    expect(within(steps[1]).queryByTestId('chip-chain')).not.toBeInTheDocument() // the bridge wallet, on Ethereum
    expect(within(steps[2]).getByTestId('chip-chain')).toHaveTextContent('BASE')
    expect(within(steps[3]).getByTestId('chip-chain')).toHaveTextContent('BASE')
    expect(screen.getAllByTestId('hop-stub')[1]).toHaveAttribute('href', expect.stringContaining('https://basescan.org/tx/'))
    expect(screen.getAllByTestId('hop-stub')[0]).toHaveAttribute('href', expect.stringContaining('https://etherscan.io/tx/'))
  })

  it('a wallet on the rail is selected by its id, so the recipient is not the suspect', () => {
    const picked: string[] = []
    render(<HopRail suspect={{ address: me, chain: c.chain }} hops={c.hop_rail} stamp={stamp} onSelect={(id) => picked.push(id)} selected={`base:${me}`} />)
    const pressed = screen.getAllByRole('button', { pressed: true })
    expect(pressed).toHaveLength(1)
    pressed[0].click()
    expect(picked).toEqual([`base:${me}`])
  })
})

describe('the fund-flow graph across a bridge', () => {
  const view = buildFlow(c)

  it('keeps the rail’s path on the first line, through the bridge and onto Base', () => {
    expect(mainPath(c).slice(0, 3)).toEqual([me, across, `base:${me}`])
    for (const id of mainPath(c)) expect(view.nodes.find((n) => n.id === id)).toMatchObject({ onPath: true, row: 0 })
  })

  it('the payout is one line from the bridge to the recipient, marked as a crossing', () => {
    const edge = view.edges.find((e) => e.id === `${across}>base:${me}`)!
    expect(edge.bridge?.bridge).toBe('Across Protocol')
    expect(edge.transfers).toHaveLength(2)
    expect(edge.onPath).toBe(true)
    const drawn = toElements(view).find((el) => el.data.id === edge.id)!
    expect(drawn.data.bridge).toBe(1)
    expect(drawn.data.label).toBe('⇄ ETH → BASE\n8,226.08 USDC')
    expect(view.edges.filter((e) => e.bridge)).toHaveLength(1)
  })

  it('a tile on another chain prints the chain’s code before the address', () => {
    expect(tileLabel(`base:${me}`)).toBe('BASE 0x21…64b0')
    expect(tileLabel(me)).toBe('0x21…64b0')
  })
})

describe('the records of a crossing', () => {
  it('the timeline has the payout as one event that carries the leg', () => {
    const events = timelineOf(c).days.flatMap((d) => d.events)
    const crossing = events.filter((e) => e.bridge)
    expect(crossing.map((e) => e.txHash).sort()).toEqual(c.crossings!.filter((x) => x.status === 'followed').map((x) => x.payout_tx!).sort())
    // in the order the money moved: the deposit, then its payout
    const at = (hash: string) => events.findIndex((e) => e.txHash === hash)
    expect(at(big.source_tx)).toBeLessThan(at(big.payout_tx!))
  })

  it('a leg states both chains, both transactions, the amounts and who matched them', () => {
    render(<BridgeLeg leg={big} />)
    const leg = screen.getByTestId('bridge-leg')
    expect(leg).toHaveTextContent('Across Protocol bridge')
    expect(leg).toHaveTextContent('7,800 USDT in · 7,777.39 USDC out · 54 s later')
    expect(leg).toHaveTextContent('Matched by the bridge’s own index (app.across.to); the amount out is read on Base. The crossing cost 22.61 USDT.')
    const [deposit, payout] = within(leg).getAllByRole('link')
    expect(deposit).toHaveAttribute('href', `https://etherscan.io/tx/${big.source_tx}`)
    expect(payout).toHaveAttribute('href', `https://basescan.org/tx/${big.payout_tx}`)
  })

  it('a deposit that could not be matched says why, in the backend’s words', () => {
    const other = c.crossings!.find((x) => x.status === 'unresolved')!
    render(<BridgeLeg leg={other} />)
    expect(screen.getByTestId('bridge-leg')).toHaveTextContent('Not matched')
    expect(screen.getByTestId('bridge-leg')).toHaveTextContent(`Not followed: ${other.reason}.`)
    expect(screen.getAllByRole('link')).toHaveLength(1)
  })

  it('the Transfers tab lists every bridge deposit, and the payout row links both explorers', () => {
    render(
      <MemoryRouter>
        <TxChains.Provider value={c.tx_chains!}>
          <TransfersTab c={c} onSelect={() => {}} />
        </TxChains.Provider>
      </MemoryRouter>,
    )
    const bridges = screen.getByRole('region', { name: 'Bridges' })
    expect(bridges).toHaveTextContent('2 of 3 deposits followed onto another chain')
    expect(within(bridges).getAllByTestId('bridge-leg')).toHaveLength(3)
    const rows = screen.getAllByTestId('bridge-row')
    expect(rows).toHaveLength(2)
    const hrefs = within(rows[0]).getAllByRole('link').map((a) => a.getAttribute('href'))
    expect(hrefs.some((h) => h?.startsWith('https://basescan.org/tx/'))).toBe(true)
    expect(hrefs.some((h) => h?.startsWith('https://etherscan.io/tx/'))).toBe(true)
  })

  it('the cost of the crossing is named as such in where the funds went', () => {
    const fee = c.where_funds_went!.find((s) => s.kind === 'bridge_fee')!
    expect(fundsName(fee)).toBe('Cost of crossing a bridge')
    expect(fee.amount).toBe(23.920992)
  })
})
