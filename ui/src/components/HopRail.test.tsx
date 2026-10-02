import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { formatAmount, formatDate, formatDuration, truncateMiddle } from '../lib/format'
import { readMock } from '../test/files'
import { setMedia } from '../test/setup'
import { HopRail } from './HopRail'

const okx = readMock<CaseDetail>('cases/demo-tron-okx.json')
const suspect = { address: okx.address, chain: okx.chain }
const stamp = { outcome: okx.outcome!, vasp: okx.top_vasp, confidence: okx.confidence, interval: okx.candidates[0].confidence_interval }
const short = (a: string) => truncateMiddle(a, 4, 4)

describe('HopRail', () => {
  it('is an ordered path: the suspect wallet, one step per hop, the stamp last', () => {
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} />)
    const rail = screen.getByRole('list', { name: 'Path of the funds' })
    const steps = within(rail).getAllByRole('listitem')
    expect(steps).toHaveLength(okx.hop_rail.length + 2)

    expect(steps[0]).toHaveTextContent('Suspect')
    expect(steps[0]).toHaveTextContent(short(okx.address))
    okx.hop_rail.forEach((hop, i) => expect(steps[i + 1]).toHaveTextContent(short(hop.to_address)))
    expect(within(steps.at(-1)!).getByTestId('outcome-stamp')).toHaveTextContent('OKX')
  })

  it('each hop carries a ticket stub: the amount, and the time since the hop before', () => {
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} />)
    const stubs = screen.getAllByTestId('hop-stub')
    expect(stubs).toHaveLength(okx.hop_rail.length)
    okx.hop_rail.forEach((hop, i) => {
      expect(stubs[i]).toHaveTextContent(formatAmount(hop.amount, hop.asset))
      expect(stubs[i]).toHaveTextContent(
        hop.elapsed_s == null ? formatDate(hop.block_time) : `${formatDuration(hop.elapsed_s)} later`.replace('same block later', 'same block'),
      )
    })
  })

  it('a stub opens its transaction on the explorer, and shows the whole hash on focus', async () => {
    const user = userEvent.setup()
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} />)
    const hop = okx.hop_rail[0]
    const stub = screen.getAllByTestId('hop-stub')[0]
    expect(stub).toHaveAttribute('href', `https://tronscan.org/#/transaction/${hop.tx_hash}`)
    expect(stub).toHaveAttribute('target', '_blank')
    act(() => stub.focus())
    expect(screen.getByRole('tooltip')).toHaveTextContent(hop.tx_hash)
    await user.keyboard('{Escape}')
  })

  it("shows the suspect's part of a transfer when the transfer carried other money too", async () => {
    const hop = { ...okx.hop_rail[1], amount: 11000, traced_amount: 5800 }
    render(<HopRail suspect={suspect} hops={[okx.hop_rail[0], hop]} stamp={stamp} />)
    const stub = screen.getAllByTestId('hop-stub')[1]
    expect(stub).toHaveTextContent('5,800 USDT')
    expect(stub).not.toHaveTextContent('11,000')
    act(() => stub.focus())
    expect(screen.getByRole('tooltip')).toHaveTextContent('5,800 USDT of a transfer of 11,000 USDT')
  })

  it('names the owner of a labelled wallet on the rail', () => {
    const last = okx.hop_rail.at(-1)!.to_address
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} labels={{ [last]: { entity: 'OKX', tier: 'derived' } }} />)
    expect(screen.getByRole('group', { name: new RegExp(`${last}, OKX, Derived by VASP-FUSION`) })).toBeInTheDocument()
  })

  it('while tracing it shows the suspect wallet and says so, with no stamp yet', () => {
    render(<HopRail suspect={suspect} hops={[]} stamp={{ outcome: null, status: 'running' }} state="tracing" />)
    expect(screen.getByText('Tracing…')).toHaveAttribute('role', 'status')
    expect(screen.queryByTestId('outcome-stamp')).not.toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
  })

  it('with no hops (the wallet is itself an exchange address) it is the wallet, then the stamp', () => {
    render(<HopRail suspect={suspect} hops={[]} stamp={stamp} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.queryByTestId('hop-stub')).not.toBeInTheDocument()
  })

  it('extends hop by hop when animated: each step waits for the one before', () => {
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} animate />)
    const steps = screen.getAllByRole('listitem')
    steps.slice(0, -1).forEach((step, i) => {
      expect(step).toHaveClass('rail-step')
      expect(step.style.getPropertyValue('--step')).toBe(String(i))
    })
    expect(steps.at(-1)).toHaveClass('rail-stamp')
    expect(steps.at(-1)!.style.getPropertyValue('--step')).toBe(String(steps.length - 1))
  })

  it('does not animate unless asked, and never when the officer asked for reduced motion', () => {
    const { unmount } = render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} />)
    for (const step of screen.getAllByRole('listitem')) expect(step).not.toHaveClass('rail-step', 'rail-stamp')
    unmount()

    setMedia('(prefers-reduced-motion: reduce)')
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} animate />)
    for (const step of screen.getAllByRole('listitem')) {
      expect(step).not.toHaveClass('rail-step')
      expect(step).not.toHaveClass('rail-stamp')
    }
  })

  it('the terminal stamp is the tilted one', () => {
    render(<HopRail suspect={suspect} hops={okx.hop_rail} stamp={stamp} />)
    expect(screen.getByTestId('outcome-stamp')).toHaveClass('stamp-tilt')
  })
})

describe('a trace that is still running', () => {
  const running = { outcome: null, status: 'running' as const }

  it('shows a place for each hop the trace has gone out so far, then the line still being drawn', () => {
    render(<HopRail suspect={suspect} hops={[]} stamp={running} state="tracing" depth={2} />)
    expect(screen.getAllByTestId('hop-pending').map((el) => el.textContent)).toEqual(['hop 1', 'hop 2'])
    expect(screen.getByText('Tracing…')).toBeInTheDocument()
  })

  it('shows none before the first hop', () => {
    render(<HopRail suspect={suspect} hops={[]} stamp={running} state="tracing" />)
    expect(screen.queryByTestId('hop-pending')).not.toBeInTheDocument()
  })
})
