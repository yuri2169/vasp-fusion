import { screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { CaseDetail, CaseSummary } from '../api/models'
import { readCase, readMock } from '../test/files'
import { renderApp } from '../test/render'
import { AbstainPanel } from './AbstainPanel'
import { AnswerPanel } from './AnswerPanel'
import { WalletPanel } from './WalletPanel'

const hero = readCase<CaseDetail>('tron-coindcx')
const two = readCase<CaseDetail>('tron-htx-coindcx')
const abstain = readCase<CaseDetail>('tron-abstain')
const bridge = readCase<CaseDetail>('eth-bridge')
const ofac = readCase<CaseDetail>('tron-ofac')
const mockSanctioned = readMock<CaseDetail>('cases/demo-tron-sanctioned.json')
const mockAbstain = readMock<CaseDetail>('cases/demo-eth-abstain.json')
const mockOkx = readMock<CaseDetail>('cases/demo-tron-okx.json')

const noop = () => {}

describe('AnswerPanel, an exchange is named', () => {
  it('asks the question the officer has, and answers with the two meters', () => {
    renderApp(<AnswerPanel c={hero} onSelect={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Why CoinDCX?' })).toBeInTheDocument()
    const card = screen.getByRole('article', { name: 'CoinDCX' })
    expect(within(card).getByRole('meter', { name: 'Proximity' })).toHaveAttribute('aria-valuetext', expect.stringContaining('1 hop'))
    expect(within(card).getByRole('meter', { name: 'Confidence' })).toHaveAttribute('aria-valuetext', expect.stringMatching(/^confidence 0\.85, range narrower than 0\.01, at or above/))
    expect(within(card).getAllByText('Derived by VASP-FUSION').length).toBeGreaterThan(0)
  })

  it('holds the one primary action: draft the request to that exchange', () => {
    renderApp(<AnswerPanel c={hero} onSelect={noop} />)
    const link = screen.getByRole('link', { name: 'Draft request to CoinDCX' })
    expect(link).toHaveAttribute('href', '/desk?vasp=CoinDCX&case=tron-coindcx')
    expect(screen.getAllByRole('link', { name: /^Draft request/ })).toHaveLength(1)
  })

  it('shows the counterfactual sentence, and that the answer holds without its strongest label', () => {
    renderApp(<AnswerPanel c={hero} onSelect={noop} />)
    expect(screen.getByText('Holds without its strongest label')).toBeInTheDocument()
    expect(screen.getByText(hero.candidates[0].counterfactual!)).toBeInTheDocument()
  })

  it('says so when a naming rests on one label', () => {
    renderApp(<AnswerPanel c={two} onSelect={noop} />)
    const htx = screen.getByRole('article', { name: 'HTX' })
    expect(within(htx).getByText('Rests on that one label')).toBeInTheDocument()
    expect(within(htx).getByRole('meter', { name: 'Confidence' })).toHaveAttribute('aria-valuetext', expect.stringMatching(/^rule confidence 0\.71/))
    // a second exchange at or above the bar can be written to as well, as a secondary action
    expect(within(htx).getByRole('link', { name: 'Draft request to HTX' })).toHaveAttribute('href', '/desk?vasp=HTX&case=tron-htx-coindcx')
  })

  it('folds the evidence of an exchange that is not the answer', async () => {
    const { user } = renderApp(<AnswerPanel c={two} onSelect={noop} />)
    const htx = screen.getByRole('article', { name: 'HTX' })
    const fold = within(htx).getByText('Evidence (3)')
    expect(fold.closest('details')).not.toHaveAttribute('open')
    await user.click(fold)
    expect(fold.closest('details')).toHaveAttribute('open')
    // the answer's own evidence is open
    expect(within(screen.getByRole('article', { name: 'CoinDCX' })).queryByText(/^Evidence \(/)).not.toBeInTheDocument()
  })

  it('lists the evidence in the backend’s words', () => {
    renderApp(<AnswerPanel c={hero} onSelect={noop} />)
    expect(screen.getByText(/^58% of the wallet's USDT \(1,530 USDT\) reached it in 1 hop$/)).toBeInTheDocument()
    expect(screen.getByText(/^Deposit-address model, for: it forwards 100%/)).toBeInTheDocument()
  })

  it('keeps an exchange that only funded the wallet apart from where the money went', () => {
    renderApp(<AnswerPanel c={hero} onSelect={noop} />)
    const funded = screen.getByRole('region', { name: 'Funded the wallet' })
    expect(within(funded).getByText('Binance')).toBeInTheDocument()
    expect(within(funded).getByText(/1% of the wallet's USDT \(14 USDT\) came from it in 1 hop/)).toBeInTheDocument()
    expect(within(funded).queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
  })

  it('keeps leads apart from the answer, and lists the next steps and the summary verbatim', () => {
    renderApp(<AnswerPanel c={hero} onSelect={noop} />)
    const leads = screen.getByRole('region', { name: 'Leads to check' })
    expect(within(leads).getByText('Lead')).toBeInTheDocument()
    const steps = screen.getByRole('region', { name: 'Next steps' })
    expect(within(steps).getAllByRole('listitem')).toHaveLength(hero.next_steps.length)
    expect(within(steps).getByText(hero.next_steps[2])).toBeInTheDocument()
    expect(screen.getByText(hero.narrative)).toBeInTheDocument()
  })

  it('selects the deposit address when its chip is used', async () => {
    const onSelect = vi.fn()
    const { user } = renderApp(<AnswerPanel c={hero} onSelect={onSelect} />)
    const card = screen.getByRole('article', { name: 'CoinDCX' })
    await user.click(within(card).getByRole('button', { name: /^Show TCw8j3/ }))
    expect(onSelect).toHaveBeenCalledWith(hero.candidates[0].deposit_address)
  })

  it('reads a mock case, which has fewer fields', () => {
    renderApp(<AnswerPanel c={mockOkx} onSelect={noop} />)
    expect(screen.getByRole('heading', { name: 'Why OKX?' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Draft request to OKX' })).toBeInTheDocument()
    const htx = screen.getByRole('article', { name: 'HTX' })
    expect(within(htx).getByText('Under the 0.60 bar')).toBeInTheDocument()
    expect(within(htx).queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
  })
})

describe('AnswerPanel, sanctioned or mixer reached', () => {
  it('leads with the alert and offers no request when no exchange was reached', () => {
    renderApp(<AnswerPanel c={ofac} onSelect={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Sanctioned address reached' })).toBeInTheDocument()
    expect(screen.getByText('Alert')).toBeInTheDocument()
    expect(screen.getByText(ofac.typology_flags[0].text)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
    expect(screen.getByText(ofac.next_steps[0])).toBeInTheDocument()
  })

  it('shows the nearest exchange, and does not offer a request under the bar', () => {
    renderApp(<AnswerPanel c={mockSanctioned} onSelect={noop} />)
    const card = screen.getByRole('article', { name: 'CoinDCX' })
    expect(within(card).getByText('Under the 0.60 bar')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
  })
})

describe('AbstainPanel', () => {
  it('says no exchange is named, and why, in the backend’s words', () => {
    renderApp(<AbstainPanel c={abstain} onSelect={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'No exchange is named' })).toBeInTheDocument()
    expect(screen.getByText(abstain.abstain_reason!)).toBeInTheDocument()
  })

  it('shows what was reached under the bar, without offering a request', () => {
    renderApp(<AbstainPanel c={abstain} onSelect={noop} />)
    const reached = screen.getByRole('region', { name: 'What was reached' })
    const card = within(reached).getByRole('article', { name: 'CoinDCX' })
    expect(within(card).getByText('Under the 0.60 bar')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Draft request/ })).not.toBeInTheDocument()
  })

  it('lists what would change the answer, the next steps, and the leads apart', () => {
    renderApp(<AbstainPanel c={abstain} onSelect={noop} />)
    const change = screen.getByRole('region', { name: 'What would change this' })
    expect(within(change).getAllByRole('listitem')).toHaveLength(abstain.what_would_change.length)
    expect(within(change).getByText(abstain.what_would_change[0])).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Next steps' })).getAllByRole('listitem')).toHaveLength(abstain.next_steps.length)
    expect(within(screen.getByRole('region', { name: 'Leads to check' })).getAllByText('Lead')).toHaveLength(2)
  })

  it('has no "what was reached" when nothing labelled was', () => {
    renderApp(<AbstainPanel c={bridge} onSelect={noop} />)
    expect(screen.queryByRole('region', { name: 'What was reached' })).not.toBeInTheDocument()
    expect(screen.getByText(bridge.what_would_change[0])).toBeInTheDocument()
  })

  it('reads a mock case, which has fewer fields', () => {
    renderApp(<AbstainPanel c={mockAbstain} onSelect={noop} />)
    expect(screen.getByText(mockAbstain.abstain_reason!)).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'ChangeNOW' })).toBeInTheDocument()
  })
})

describe('WalletPanel', () => {
  const deposit = hero.graph.nodes[1]
  const lead = hero.graph.nodes.find((n) => n.id.startsWith('TDYCQE'))!

  it('prints the address whole and says what the wallet is', () => {
    renderApp(<WalletPanel c={hero} id={deposit.id} onSelect={noop} onClose={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Deposit address' })).toBeInTheDocument()
    expect(screen.getByText(deposit.id)).toBeInTheDocument()
    expect(screen.getByText('1 hop from the suspect wallet')).toBeInTheDocument()
  })

  it('shows the label: owner, tier, source, and its evidence verbatim', () => {
    renderApp(<WalletPanel c={hero} id={deposit.id} onSelect={noop} onClose={noop} />)
    const label = screen.getByRole('region', { name: 'Label' })
    expect(within(label).getByText('CoinDCX')).toBeInTheDocument()
    expect(within(label).getByText('Derived by VASP-FUSION', { selector: 'span' })).toBeInTheDocument()
    expect(within(label).getByText('vaspfusion-discover')).toBeInTheDocument()
    expect(within(label).getByText(deposit.label!.evidence!)).toBeInTheDocument()
  })

  it('says "confidence" with its range for a model-confirmed label, and never prints 1.00', () => {
    renderApp(<WalletPanel c={hero} id={deposit.id} onSelect={noop} onClose={noop} />)
    const label = screen.getByRole('region', { name: 'Label' })
    expect(within(label).getByText(/^confidence 0\.85, range narrower than 0\.01$/)).toBeInTheDocument()
    expect(within(label).getByText(/Deposit-address model: over 0\.99/)).toBeInTheDocument()
    expect(label).not.toHaveTextContent('1.00')
    expect(within(label).getAllByTestId('reason-bar')).toHaveLength(3)
  })

  it('says "rule confidence" for a label the model did not confirm', () => {
    const cluster = { ...deposit, label: { ...deposit.label!, confidence_low: null, confidence_high: null, model: null, confidence: 0.855 } }
    const c = { ...hero, graph: { ...hero.graph, nodes: hero.graph.nodes.map((n) => (n.id === deposit.id ? cluster : n)) } }
    renderApp(<WalletPanel c={c} id={deposit.id} onSelect={noop} onClose={noop} />)
    expect(screen.getByText('rule confidence 0.85')).toBeInTheDocument()
  })

  it('says an unlabelled wallet has no label, and shows the pattern seen on it', () => {
    renderApp(<WalletPanel c={hero} id={lead.id} onSelect={noop} onClose={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Wallet on the trail' })).toBeInTheDocument()
    expect(screen.getByText('No label in any source.')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Patterns on this wallet' })).getByText('Lead')).toBeInTheDocument()
  })

  it('lists what came in and what went out on this trail, each with its transaction', () => {
    renderApp(<WalletPanel c={hero} id={lead.id} onSelect={noop} onClose={noop} />)
    const money = screen.getByRole('region', { name: 'On this trail' })
    expect(within(money).getByText(/Received/)).toHaveTextContent('Received 1,122.22 USDT in 1 transfer')
    expect(within(money).getByText(/Passed on/)).toHaveTextContent('Passed on 1,122.22 USDT in 1 transfer')
    const hashes = hero.graph.edges.filter((e) => e.source === lead.id || e.target === lead.id).map((e) => e.tx_hash)
    for (const hash of hashes) expect(within(money).getByRole('group', { name: `Transaction ${hash}` })).toBeInTheDocument()
  })

  it('moves to the wallet on the other side of a transfer', async () => {
    const onSelect = vi.fn()
    const { user } = renderApp(<WalletPanel c={hero} id={lead.id} onSelect={onSelect} onClose={noop} />)
    await user.click(screen.getByRole('button', { name: /^Show TDqSqu/ }))
    expect(onSelect).toHaveBeenCalledWith(hero.graph.nodes.find((n) => n.id.startsWith('TDqSqu'))!.id)
  })

  it('goes back to the answer', async () => {
    const onClose = vi.fn()
    const { user } = renderApp(<WalletPanel c={hero} id={lead.id} onSelect={noop} onClose={onClose} />)
    await user.click(screen.getByRole('button', { name: 'Back to the answer' }))
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('opens a case for the wallet, and shows the server’s sentence when it cannot', async () => {
    const open = vi.spyOn(api, 'openCase').mockResolvedValueOnce({ id: 'c-0123456789' } as CaseSummary)
    const { user } = renderApp(<WalletPanel c={hero} id={lead.id} onSelect={noop} onClose={noop} />)
    await user.click(screen.getByRole('button', { name: 'Open a case for this wallet' }))
    expect(open).toHaveBeenCalledWith({ address: lead.id, chain: 'tron' }, undefined)
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/cases/c-0123456789'))

    open.mockRejectedValueOnce(new ApiError(422, 'OFFLINE=1 and not cached. Trace it with the network on.'))
    // the button is disabled while the first request settles
    await user.click(await screen.findByRole('button', { name: 'Open a case for this wallet' }))
    expect(await screen.findByText('OFFLINE=1 and not cached. Trace it with the network on.')).toBeInTheDocument()
  })

  it('does not offer a case for the wallet the case is already about', () => {
    renderApp(<WalletPanel c={hero} id={hero.address} onSelect={noop} onClose={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'Suspect wallet' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Open a case for this wallet' })).not.toBeInTheDocument()
  })

  it('lists the wallets of a group', async () => {
    const onSelect = vi.fn()
    const { user } = renderApp(<WalletPanel c={mockOkx} id="cluster:OKX" onSelect={onSelect} onClose={noop} />)
    expect(screen.getByRole('heading', { level: 2, name: 'OKX' })).toBeInTheDocument()
    expect(screen.getByText('2 wallets of this exchange are in the case')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Show THS5KL/ }))
    expect(onSelect).toHaveBeenCalledWith(mockOkx.graph.nodes.find((n) => n.id.startsWith('THS5KL'))!.id)
  })

  it('says so when the wallet is not in this case', () => {
    renderApp(<WalletPanel c={hero} id="TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX" onSelect={noop} onClose={noop} />)
    expect(screen.getByText('This wallet is not part of this case.')).toBeInTheDocument()
  })
})
