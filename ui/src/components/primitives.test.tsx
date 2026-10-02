import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Chain, Tier, TypologyFlag as Flag } from '../api/models'
import { Amount } from './Amount'
import { Button } from './Button'
import { ChainBadge } from './ChainBadge'
import { CopyButton } from './CopyButton'
import { EmptyState } from './EmptyState'
import { ErrorState } from './ErrorState'
import { Skeleton } from './Skeleton'
import { TierTag } from './TierTag'
import { TypologyFlag } from './TypologyFlag'

describe('Button', () => {
  it('is a plain button that does not submit a form by accident', () => {
    render(<Button>Trace wallet</Button>)
    expect(screen.getByRole('button', { name: 'Trace wallet' })).toHaveAttribute('type', 'button')
  })

  it('only the primary action is saffron', () => {
    render(
      <>
        <Button variant="primary">Draft request to OKX</Button>
        <Button>Open case file</Button>
        <Button variant="danger">Withdraw request</Button>
      </>,
    )
    expect(screen.getByRole('button', { name: 'Draft request to OKX' })).toHaveClass('bg-saffron', 'text-saffron-on')
    expect(screen.getByRole('button', { name: 'Open case file' })).not.toHaveClass('bg-saffron')
    expect(screen.getByRole('button', { name: 'Withdraw request' })).toHaveClass('bg-seal')
  })

  it('does nothing when disabled', async () => {
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Trace wallet</Button>)
    await userEvent.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('CopyButton', () => {
  it('copies the whole value and says so', async () => {
    const user = userEvent.setup()
    render(<CopyButton value="TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c" label="address" />)
    await user.click(screen.getByRole('button', { name: 'Copy address' }))
    expect(await navigator.clipboard.readText()).toBe('TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c')
    expect(screen.getByRole('status')).toHaveTextContent('Copied')
  })
})

describe('ChainBadge', () => {
  it.each<[Chain, string, string]>([
    ['tron', 'TRON', 'Tron'],
    ['ethereum', 'ETH', 'Ethereum'],
    ['bsc', 'BSC', 'BNB Smart Chain'],
    ['polygon', 'POLYGON', 'Polygon'],
    ['arbitrum', 'ARB', 'Arbitrum'],
    ['base', 'BASE', 'Base'],
    ['optimism', 'OP', 'Optimism'],
    ['avalanche', 'AVAX', 'Avalanche'],
    ['bitcoin', 'BTC', 'Bitcoin'],
    ['solana', 'SOL', 'Solana'],
  ])('%s prints %s and is named %s', (chain, code, name) => {
    render(<ChainBadge chain={chain} />)
    const badge = screen.getByText(code)
    expect(badge.closest('[title]')).toHaveAttribute('title', name)
  })

  it('a guess while typing is marked as one, in words', () => {
    render(<ChainBadge chain="tron" tentative />)
    expect(screen.getByText('TRON').closest('[title]')).toHaveAttribute('title', 'Looks like Tron')
    expect(screen.getByText('TRON').closest('[title]')).toHaveClass('border-dashed')
  })
})

describe('TierTag', () => {
  it.each<[Tier | null, string]>([
    ['published_por', 'Published by exchange'],
    ['curated', 'Curated list'],
    ['explorer_tag', 'Explorer tag'],
    ['derived', 'Derived by VASP-FUSION'],
    [null, 'Unlabelled'],
  ])('%s reads "%s", with an icon', (tier, name) => {
    const { container } = render(<TierTag tier={tier} />)
    expect(screen.getByText(name)).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
    expect(container.firstElementChild).toHaveAttribute('data-tier', tier ?? 'none')
  })
})

describe('Amount', () => {
  it('is set in mono with tabular figures', () => {
    render(<Amount value={2652.22} asset="USDT" />)
    const amount = screen.getByText('2,652.22').closest('.font-mono')
    expect(amount).toHaveClass('tabular')
    expect(amount).toHaveTextContent('2,652.22 USDT')
  })

  it('adds the US dollar value when there is one', () => {
    render(<Amount value={0.002428} asset="ETH" usd={9.71} />)
    expect(screen.getByText('$9.71')).toBeInTheDocument()
  })

  it('does not repeat the figure for a dollar stablecoin', () => {
    render(<Amount value={48500} asset="USDT" usd={48500} />)
    expect(screen.queryByText('$48,500')).not.toBeInTheDocument()
  })

  it('shows no dollar value when there is none (Bitcoin has no price feed)', () => {
    const { container } = render(<Amount value={0.364594} asset="BTC" usd={null} />)
    expect(container).toHaveTextContent('0.364594 BTC')
    expect(container).not.toHaveTextContent('$')
  })
})

describe('TypologyFlag', () => {
  const flag = (code: Flag['code'], severity: Flag['severity']): Flag => ({
    code,
    severity,
    wallet: 'TTYBTvGc7m45x7j6Vr6YnTDgVfgjnqq62o',
    text: 'TTYBTv…nqq62o passed on 100% of the 48,500 USDT that reached it within 9 minutes of its arrival',
    figures: {},
    tx_hashes: [],
  })

  it.each<[Flag['code'], Flag['severity'], string, string]>([
    ['sanctioned_contact', 'high', 'Sanctioned contact', 'Alert'],
    ['mixer_contact', 'high', 'Mixer contact', 'Alert'],
    ['bridge_hop', 'warn', 'Bridge', 'Pattern'],
    ['peel_chain', 'warn', 'Peel chain', 'Pattern'],
    ['rapid_forwarding', 'warn', 'Rapid forwarding', 'Pattern'],
    ['coinjoin_shape', 'warn', 'CoinJoin shape', 'Pattern'],
    ['fan_out', 'info', 'Fan-out', 'Note'],
    ['fan_in', 'info', 'Fan-in', 'Note'],
    ['round_amounts', 'info', 'Round amounts', 'Note'],
    ['deposit_like', 'info', 'Behaves like a deposit address', 'Lead'],
  ])('%s (%s) is named "%s" and marked "%s" in words', (code, severity, name, word) => {
    const { container } = render(<TypologyFlag flag={flag(code, severity)} />)
    expect(screen.getByText(name)).toBeInTheDocument()
    expect(screen.getByText(word)).toBeInTheDocument()
    expect(container.querySelector('svg')).toBeInTheDocument()
  })

  it("shows the backend's sentence, and leaves it out when compact", () => {
    const f = flag('rapid_forwarding', 'warn')
    const { rerender } = render(<TypologyFlag flag={f} />)
    expect(screen.getByText(f.text)).toBeInTheDocument()
    rerender(<TypologyFlag flag={f} compact />)
    expect(screen.queryByText(f.text)).not.toBeInTheDocument()
    expect(screen.getByText('Rapid forwarding')).toBeInTheDocument()
  })
})

describe('EmptyState', () => {
  it('invites the next action', () => {
    render(
      <EmptyState title="No cases yet" action={<Button variant="primary">Trace wallet</Button>}>
        Paste a wallet address to open a case.
      </EmptyState>,
    )
    expect(screen.getByRole('heading', { name: 'No cases yet' })).toBeInTheDocument()
    expect(screen.getByText('Paste a wallet address to open a case.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trace wallet' })).toBeInTheDocument()
  })
})

describe('ErrorState', () => {
  it('is announced, says what happened, and offers to try again', async () => {
    const onRetry = vi.fn()
    render(
      <ErrorState
        title="The cases could not be loaded"
        detail="Cannot reach the VASP-FUSION server. Check that it is running, then try again."
        onRetry={onRetry}
      />,
    )
    const alert = screen.getByRole('alert')
    expect(within(alert).getByText('The cases could not be loaded')).toBeInTheDocument()
    expect(within(alert).getByText(/Check that it is running/)).toBeInTheDocument()
    await userEvent.click(within(alert).getByRole('button', { name: 'Try again' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('has no button when there is nothing to retry', () => {
    render(<ErrorState title="Not found" detail="No case has this id. Check the link." />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})

describe('Skeleton', () => {
  it('is hidden from screen readers and can stand for several lines', () => {
    const { container } = render(<Skeleton lines={3} />)
    expect(container.querySelectorAll('.skeleton')).toHaveLength(3)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
  })
})
