import { screen, waitFor, within } from '@testing-library/react'
import { expect, it } from 'vitest'
import { AppRoutes } from '../App'
import { renderApp } from '../test/render'

const SECTIONS = [
  'Colour',
  'Type',
  'Buttons',
  'Addresses and hashes',
  'Chains',
  'Label tiers',
  'Outcome stamps',
  'Proximity and confidence',
  'Amounts',
  'Patterns and leads',
  'Hop Rail',
  'Where the funds went',
  'Evidence',
  'Tabs',
  'Table',
  'Empty, loading and error',
  'Charts',
  'Toast and dialog',
]

it('shows every component, in every state, on one page', async () => {
  const { user } = renderApp(<AppRoutes />, { route: '/kit' })
  expect(await screen.findByRole('heading', { level: 1, name: 'Component kit' })).toBeInTheDocument()
  for (const name of SECTIONS) expect(screen.getByRole('heading', { level: 2, name })).toBeInTheDocument()

  // the fixtures arrive through the API client
  await waitFor(() => expect(screen.getAllByRole('list', { name: 'Path of the funds' }).length).toBeGreaterThanOrEqual(4))

  const outcomes = new Set(screen.getAllByTestId('outcome-stamp').map((s) => s.getAttribute('data-outcome')))
  for (const o of ['ATTRIBUTED', 'INSUFFICIENT_EVIDENCE', 'SANCTIONED_OR_MIXER_REACHED', 'running', 'failed']) expect(outcomes).toContain(o)

  for (const tier of ['published_por', 'curated', 'explorer_tag', 'derived', 'none'])
    expect(document.querySelector(`[data-tier="${tier}"]`), tier).toBeInTheDocument()

  for (const code of ['TRON', 'ETH', 'BNB', 'POLYGON', 'ARB', 'BASE', 'OP', 'AVAX', 'BTC', 'SOL'])
    expect(screen.getAllByText(code).length, code).toBeGreaterThan(0)

  expect(screen.getAllByRole('meter', { name: 'Proximity' }).length).toBeGreaterThanOrEqual(4)
  expect(screen.getByRole('table', { name: 'Labelled addresses' })).toBeInTheDocument()
  expect(await screen.findByRole('group', { name: /^Reliability plot/ })).toBeInTheDocument()
  expect(screen.getByRole('list', { name: 'Finished cases by outcome' })).toBeInTheDocument()

  // toast and dialog work from the page
  await user.click(screen.getByRole('button', { name: 'Show a toast' }))
  expect(screen.getByText('Marked as sent')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Open a dialog' }))
  expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Withdraw request' })).toBeInTheDocument()
})

it('says the figures on the page are demo fixtures', async () => {
  renderApp(<AppRoutes />, { route: '/kit' })
  expect(await screen.findByText(/demonstration fixtures/)).toBeInTheDocument()
})
