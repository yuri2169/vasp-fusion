import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { CaseDetail } from '../api/models'
import { readCase, readMock } from '../test/files'
import { renderApp } from '../test/render'
import { AddressChip } from './AddressChip'
import { EvidenceList } from './EvidenceList'
import { FundsBar } from './FundsBar'
import { HopRail } from './HopRail'
import { Tabs } from './Tabs'

const hero = readCase<CaseDetail>('tron-coindcx')
const bridge = readCase<CaseDetail>('eth-bridge')
const ofac = readCase<CaseDetail>('tron-ofac')
const okx = readMock<CaseDetail>('cases/demo-tron-okx.json')

describe('Tabs', () => {
  const TABS = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'transfers', label: 'Transfers', count: 8 },
    { id: 'audit', label: 'Audit' },
  ]
  function Demo({ onChange = () => {} }: { onChange?: (id: string) => void }) {
    const [active, setActive] = useState('timeline')
    return (
      <Tabs
        label="Case records"
        tabs={TABS}
        active={active}
        onChange={(id) => {
          setActive(id)
          onChange(id)
        }}
      >
        <p>Panel of {active}</p>
      </Tabs>
    )
  }

  it('is a tab list with one tab selected and its panel labelled by it', () => {
    render(<Demo />)
    const list = screen.getByRole('tablist', { name: 'Case records' })
    const tabs = within(list).getAllByRole('tab')
    expect(tabs.map((t) => t.getAttribute('aria-selected'))).toEqual(['true', 'false', 'false'])
    expect(screen.getByRole('tabpanel', { name: 'Timeline' })).toHaveTextContent('Panel of timeline')
  })

  it('says how many records a tab holds', () => {
    render(<Demo />)
    expect(screen.getByRole('tab', { name: 'Transfers 8' })).toBeInTheDocument()
  })

  it('opens a tab on click', async () => {
    const onChange = vi.fn()
    render(<Demo onChange={onChange} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Audit' }))
    expect(onChange).toHaveBeenCalledWith('audit')
    expect(screen.getByRole('tabpanel', { name: 'Audit' })).toHaveTextContent('Panel of audit')
  })

  it('keeps one tab stop, and moves with the arrow keys, Home and End', async () => {
    const user = userEvent.setup()
    render(<Demo />)
    const [timeline, transfers, audit] = screen.getAllByRole('tab')
    expect([timeline.tabIndex, transfers.tabIndex, audit.tabIndex]).toEqual([0, -1, -1])
    timeline.focus()
    await user.keyboard('{ArrowRight}')
    expect(transfers).toHaveFocus()
    expect(transfers).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{End}')
    expect(audit).toHaveFocus()
    await user.keyboard('{ArrowRight}') // wraps
    expect(timeline).toHaveFocus()
    await user.keyboard('{ArrowLeft}')
    expect(audit).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{Home}')
    expect(timeline).toHaveAttribute('aria-selected', 'true')
  })
})

describe('FundsBar', () => {
  const segments = () => screen.getAllByTestId('funds-segment')

  it('draws one segment per slice, as wide as its share', () => {
    render(<FundsBar slices={hero.where_funds_went} asset="USDT" total={hero.total_sent} named="CoinDCX" />)
    expect(segments().map((s) => s.style.flexBasis)).toEqual(['57.7%', '42.3%'])
  })

  it('gives saffron to the exchange the case names, and to nothing else', () => {
    render(<FundsBar slices={hero.where_funds_went} asset="USDT" total={hero.total_sent} named="CoinDCX" />)
    expect(segments().map((s) => s.dataset.fill)).toEqual(['named', 'open'])
  })

  it('marks sanctioned money in red, other named parties in ink, and what is unresolved hatched', () => {
    const { unmount } = render(<FundsBar slices={ofac.where_funds_went} asset="USDT" total={ofac.total_sent} />)
    expect(segments().map((s) => s.dataset.fill)).toEqual(['seal', 'open', 'open'])
    unmount()
    render(<FundsBar slices={bridge.where_funds_went} asset="USDT" total={bridge.total_sent} />)
    // the money that crossed the Across bridge was followed onto Base: it is past the hop limit there, not "at a bridge"
    expect(segments().map((s) => s.dataset.fill)).toEqual(['open', 'party', 'open', 'open', 'party', 'open', 'open'])
  })

  it('names every slice in words, with its share and amount', () => {
    render(<FundsBar slices={bridge.where_funds_went} asset="USDT" total={bridge.total_sent} />)
    const legend = screen.getByRole('list', { name: 'Where the funds went' })
    const rows = within(legend).getAllByRole('listitem').map((li) => li.textContent)
    expect(rows[0]).toMatch(/Past the hop limit.*62%.*8,546\.08 USDT/)
    expect(rows[1]).toMatch(/Uniswap V4.*25%.*3,471\.12 USDT/)
    expect(rows[3]).toMatch(/Busy unlabelled wallets.*4%/)
    expect(rows[4]).toMatch(/Optimism \(bridge\).*4%.*500 USDT/)
    expect(rows[5]).toMatch(/Cost of crossing a bridge.*under 1%.*23\.92 USDT/)
    expect(rows[6]).toMatch(/Came back to the wallet.*under 1%/)
    expect(screen.getByText('Where the 13,705.05 USDT went')).toBeInTheDocument()
  })

  it('reads as one sentence to a screen reader', () => {
    render(<FundsBar slices={hero.where_funds_went} asset="USDT" total={hero.total_sent} named="CoinDCX" />)
    expect(screen.getByRole('img')).toHaveAccessibleName('58% CoinDCX, 42% Busy unlabelled wallets')
  })

  it('is not drawn for a case that carries no breakdown', () => {
    const { container } = render(<FundsBar slices={okx.where_funds_went} asset="USDT" total={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('EvidenceList', () => {
  const evidence = hero.candidates[0].evidence

  it('shows every sentence as the backend wrote it', () => {
    render(<EvidenceList items={evidence} chain="tron" />)
    for (const item of evidence.filter((e) => e.kind !== 'counterfactual')) expect(screen.getByText(item.text)).toBeInTheDocument()
  })

  it('leaves the counterfactual to the card that shows it', () => {
    render(<EvidenceList items={evidence} chain="tron" />)
    expect(screen.queryByText(/^Still CoinDCX without the label/)).not.toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(evidence.length - 1)
  })

  it('names the tier of a label and links every transaction that proves an item', () => {
    render(<EvidenceList items={evidence} chain="tron" />)
    expect(screen.getByText('Derived by VASP-FUSION')).toBeInTheDocument()
    const hash = evidence.find((e) => e.kind === 'path')!.tx_hashes[0]
    expect(screen.getByRole('group', { name: `Transaction ${hash}` })).toBeInTheDocument()
  })

  it('draws the model’s reasons as signed bars, and its probability without one', () => {
    render(<EvidenceList items={evidence} chain="tron" />)
    const bars = screen.getAllByTestId('reason-bar')
    expect(bars).toHaveLength(3)
    expect(bars.map((b) => b.dataset.sign)).toEqual(['for', 'for', 'for'])
    // the strongest reason is the full width
    expect(bars[0].style.width).toBe('100%')
    expect(Number.parseFloat(bars[2].style.width)).toBeCloseTo((1.6002 / 2.2923) * 100, 0)
    expect(screen.getByText('+2.29')).toBeInTheDocument()
  })

  it('draws a reason against as against', () => {
    const against = [{ kind: 'model' as const, text: 'Deposit-address model, against: it keeps a balance', tx_hashes: [], weight: -0.8, tier: null }]
    render(<EvidenceList items={against} chain="tron" />)
    expect(screen.getByTestId('reason-bar').dataset.sign).toBe('against')
    expect(screen.getByText('−0.80')).toBeInTheDocument()
  })

  it('is not drawn when there is nothing', () => {
    const { container } = render(<EvidenceList items={[]} chain="tron" />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('selecting a wallet', () => {
  it('turns the address of a chip into a button that says whether it is selected', async () => {
    const onSelect = vi.fn()
    const { user } = renderApp(<AddressChip address={hero.address} chain="tron" onSelect={onSelect} selected />)
    const button = screen.getByRole('button', { name: /Show TYJD2h…e2HP1c/ })
    expect(button).toHaveAttribute('aria-pressed', 'true')
    await user.click(button)
    expect(onSelect).toHaveBeenCalledOnce()
  })

  it('has no such button when nothing can be selected', () => {
    renderApp(<AddressChip address={hero.address} chain="tron" />)
    expect(screen.queryByRole('button', { name: /^Show / })).not.toBeInTheDocument()
  })

  it('lets a wallet on the Hop Rail be selected, and marks the path to the selection', async () => {
    const onSelect = vi.fn()
    const path = [okx.hop_rail[0].from_address, okx.hop_rail[0].to_address]
    const { user } = renderApp(
      <HopRail
        suspect={{ address: okx.address, chain: okx.chain }}
        hops={okx.hop_rail}
        stamp={{ outcome: okx.outcome ?? null, status: okx.status, vasp: okx.top_vasp, confidence: okx.confidence }}
        selected={path[1]}
        marked={new Set(path)}
        onSelect={onSelect}
      />,
    )
    const chips = within(screen.getByRole('list', { name: 'Path of the funds' })).getAllByRole('group', { name: /Tron address/ })
    expect(chips.map((c) => c.dataset.marked)).toEqual(['true', 'true', undefined, undefined])
    expect(chips.map((c) => c.dataset.selected)).toEqual([undefined, 'true', undefined, undefined])
    await user.click(within(chips[2]).getByRole('button', { name: /^Show / }))
    expect(onSelect).toHaveBeenCalledWith(okx.hop_rail[1].to_address)
  })

  it('carries a footer inside the rail’s card', () => {
    renderApp(
      <HopRail
        suspect={{ address: okx.address, chain: okx.chain }}
        hops={okx.hop_rail}
        stamp={{ outcome: okx.outcome ?? null, status: okx.status, vasp: okx.top_vasp }}
        footer={<p>Where the funds went</p>}
      />,
    )
    expect(screen.getByText('Where the funds went')).toBeInTheDocument()
  })
})
