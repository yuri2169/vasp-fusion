import cytoscape from 'cytoscape'
import { describe, expect, it } from 'vitest'
import type { CaseDetail, Tier } from '../api/models'
import { buildFlow, nodeXY, type Role } from '../lib/caseGraph'
import { MOCK_CASES, REAL_CASES, readCase, readMock } from '../test/files'
import { FALLBACK_THEME, ROLE_SHAPES, stylesheet, toElements } from './flowStyle'

const hero = readCase<CaseDetail>('tron-coindcx')
const okx = readMock<CaseDetail>('cases/demo-tron-okx.json')
const everyCase = () => [...MOCK_CASES.map((id) => readMock<CaseDetail>(`cases/${id}.json`)), ...REAL_CASES.map((id) => readCase<CaseDetail>(id))]

const ROLES: Role[] = [
  'suspect', 'intermediary', 'exchange_hot', 'exchange_deposit', 'exchange', 'custodial_wallet',
  'swap_service', 'bridge', 'mixer', 'sanctioned', 'hub', 'unknown',
]
const TIERS: (Tier | 'none')[] = ['published_por', 'curated', 'explorer_tag', 'derived', 'none']

describe('toElements', () => {
  const view = buildFlow(hero)
  const elements = toElements(view)
  const wallet = (start: string) => elements.find((e) => e.group === 'nodes' && String(e.data.id).startsWith(start))!
  const captions = elements.filter((e) => e.classes === 'caption')

  it('places every wallet where the layout says', () => {
    for (const n of view.nodes) expect(elements.find((e) => e.data.id === n.id)!.position).toEqual(nodeXY(n))
  })

  it('carries what the picture encodes: role, tier, the named exchange, the main path', () => {
    expect(wallet('TCw8j3').data).toMatchObject({ role: 'exchange_deposit', tier: 'derived', named: 1, onPath: 1, kind: 'wallet' })
    expect(wallet('TYJD2h').data).toMatchObject({ role: 'suspect', tier: 'none', named: 0, onPath: 1 })
    expect(wallet('TYASr5').data).toMatchObject({ role: 'exchange', tier: 'curated', named: 0, onPath: 0 })
  })

  it('writes the address under an unlabelled wallet in short form, and the owner over a labelled one', () => {
    expect(wallet('TDYCQE').data.label).toBe('TDYC…dsUJ')
    expect(captions.map((c) => c.data.label).sort()).toEqual(['Binance', 'Busy wallet', 'CoinDCX', 'Suspect'])
    const caption = captions.find((c) => c.data.label === 'CoinDCX')!
    expect(caption.data.owner).toBe(wallet('TCw8j3').data.id)
    expect(caption.position!.y).toBeLessThan(wallet('TCw8j3').position!.y)
    expect(caption.selectable).toBe(false)
  })

  it('draws an edge as wide as its amount, with the amount written on the larger ones', () => {
    const edges = elements.filter((e) => e.group === 'edges')
    expect(edges).toHaveLength(view.edges.length)
    const funding = edges.find((e) => String(e.data.source).startsWith('TT9b4u'))!
    expect(funding.data).toMatchObject({ width: 4.4, inbound: 1, onPath: 0, label: '2,332 USDT' })
    const dust = edges.find((e) => String(e.data.source).startsWith('TYASr5'))!
    expect(dust.data.width).toBeLessThan(3)
    expect(dust.data.label).toBe('')
  })

  it('writes each amount in the asset that moved, also when a case holds two assets', () => {
    const mixed = toElements(buildFlow(readMock<CaseDetail>('cases/demo-eth-abstain.json')))
    const labels = mixed.filter((e) => e.group === 'edges').map((e) => e.data.label)
    expect(labels).toContain('9,900 USDT')
    expect(labels).toContain('6.20 ETH')
  })

  it('says how many wallets a group stands for', () => {
    const grouped = toElements(buildFlow(okx, { collapse: true }))
    const group = grouped.find((e) => e.data.id === 'cluster:OKX')!
    expect(group.data).toMatchObject({ kind: 'cluster', label: '2 wallets', named: 1 })
  })

  it('is accepted by Cytoscape for every case, grouped or not', () => {
    for (const c of everyCase())
      for (const collapse of [false, true]) {
        const cy = cytoscape({ headless: true, elements: toElements(buildFlow(c, { collapse })), style: stylesheet(FALLBACK_THEME) })
        expect(cy.nodes().length, c.id).toBeGreaterThan(0)
        expect(cy.edges().length, c.id).toBe(buildFlow(c, { collapse }).edges.length)
        cy.destroy()
      }
  })
})

describe('the stylesheet', () => {
  const rules = stylesheet(FALLBACK_THEME)
  const selectors = rules.map((r) => r.selector)

  it('has a shape for every role', () => {
    for (const role of ROLES) {
      expect(ROLE_SHAPES[role].shape, role).toBeTruthy()
      expect(selectors, role).toContain(`node[role = "${role}"]`)
    }
    // told apart by shape, not by colour: no two kinds of labelled party share one
    const shapes = (['exchange', 'exchange_deposit', 'bridge', 'mixer', 'sanctioned', 'hub', 'suspect'] as Role[]).map((r) => ROLE_SHAPES[r].shape)
    expect(new Set(shapes).size).toBe(shapes.length)
  })

  it('has a border for every label tier, each of a different style', () => {
    const styles = TIERS.map((tier) => {
      const rule = rules.find((r) => r.selector === `node[tier = "${tier}"]`)
      expect(rule, tier).toBeDefined()
      return (rule as unknown as { style: Record<string, unknown> }).style['border-style']
    })
    expect(new Set(styles).size).toBeGreaterThanOrEqual(4)
  })

  it('keeps saffron for the exchange the case names', () => {
    const saffron = rules.filter((r) => JSON.stringify(r).includes(FALLBACK_THEME.saffron))
    expect(saffron.map((r) => r.selector)).toEqual(['node[named = 1]'])
  })
})
