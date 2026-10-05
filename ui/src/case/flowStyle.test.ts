import cytoscape from 'cytoscape'
import { describe, expect, it } from 'vitest'
import type { CaseDetail, Tier } from '../api/models'
import { buildFlow, fanId, nodeXY, type Role } from '../lib/caseGraph'
import { fanCase } from '../../scripts/big-graph.mjs'
import { MOCK_CASES, REAL_CASES, readCase, readMock } from '../test/files'
import { FALLBACK_THEME, TILE, iconUri, stylesheet, textBoxes, tileLook, tileSize, toElements, type Box } from './flowStyle'
import { ROLE_ICONS } from './roleIcons'

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
    // one of three payers: its line is a fan's, and the amount is written beside the payer
    expect(funding.data).toMatchObject({ width: 4.4, inbound: 1, onPath: 0, fan: 'in', stub: '2,332 USDT', label: '' })
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

  it('draws every role as a square tile with an icon of its own', () => {
    expect((rules.find((r) => r.selector === 'node') as unknown as { style: Record<string, unknown> }).style.shape).toBe('rectangle')
    for (const role of ROLES) expect(selectors, role).toContain(`node[role = "${role}"]`)
    // told apart by the icon, not by colour: no two kinds of party share one
    const kinds = (['suspect', 'intermediary', 'hub', 'exchange', 'exchange_deposit', 'custodial_wallet', 'swap_service', 'bridge', 'mixer', 'sanctioned'] as Role[]).map((r) => ROLE_ICONS[r])
    expect(kinds.every(Boolean)).toBe(true)
    expect(new Set(kinds).size).toBe(kinds.length)
    // a wallet not followed further is a bare tile
    expect(ROLE_ICONS.unknown).toBeNull()
  })

  it('draws the icon as an image the canvas can read, in a colour that is not the fill', () => {
    for (const role of ROLES) {
      const look = tileLook(role, FALLBACK_THEME)
      expect(look.ink, role).not.toBe(look.fill)
      const node = ROLE_ICONS[role]
      if (!node) continue
      const uri = iconUri(node, look.ink)
      expect(uri.startsWith('data:image/svg+xml;utf8,')).toBe(true)
      const svg = decodeURIComponent(uri.slice('data:image/svg+xml;utf8,'.length))
      expect(svg).toContain(`stroke="${look.ink}"`)
      expect(new DOMParser().parseFromString(svg, 'image/svg+xml').querySelector('parsererror')).toBeNull()
    }
  })

  it('has three tile sizes, by the amount that passed through', () => {
    const view = buildFlow(hero, { collapse: false })
    const most = Math.max(...view.nodes.map((n) => Math.max(n.received, n.sent)))
    const node = (over: Partial<(typeof view.nodes)[number]>) => ({ ...view.nodes.find((n) => n.role !== 'suspect')!, ...over })
    expect(tileSize(node({ received: most, sent: 0 }), most)).toBe('l')
    expect(tileSize(node({ received: most * 0.2, sent: 0 }), most)).toBe('m')
    expect(tileSize(node({ received: most * 0.01, sent: 0 }), most)).toBe('s')
    expect(tileSize(view.nodes.find((n) => n.role === 'suspect')!, most)).toBe('l')
    const sides = new Set(toElements(view).filter((e) => e.group === 'nodes' && e.data.side).map((e) => e.data.side))
    for (const side of sides) expect([...Object.values(TILE), 16]).toContain(side)
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

describe('a fan on the canvas', () => {
  const fifty = fanCase(50)
  // made afresh for each use: Cytoscape keeps and changes the elements it is given
  const closed = () => toElements(buildFlow(fifty))
  const open = () => toElements(buildFlow(fifty, { openFans: new Set([fanId('in', fifty.address)]) }))
  const overlap = (a: Box, b: Box) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2

  it('draws the group as one node that says how many wallets and how much', () => {
    const group = closed().find((e) => e.data.kind === 'fan')!
    expect(group.data.label).toMatch(/^46 wallets paid in\n[\d,.]+ USDT$/)
    const line = closed().find((e) => e.group === 'edges' && e.data.source === group.data.id)!
    expect(line.data).toMatchObject({ fan: 'in', label: '' })
    expect(line.data.stub).toBeUndefined()
  })

  it('routes every line of the fan square, and Cytoscape accepts it', () => {
    const rule = stylesheet(FALLBACK_THEME).find((r) => r.selector === 'edge[fan]') as unknown as { style: Record<string, unknown> }
    expect(rule.style).toMatchObject({ 'curve-style': 'taxi', 'taxi-direction': 'rightward' })
    for (const elements of [closed(), open()]) {
      const cy = cytoscape({ headless: true, elements, style: stylesheet(FALLBACK_THEME) })
      const inbound = cy.edges('[inbound = 1]')
      expect(inbound.length).toBeGreaterThan(4)
      expect(cy.edges('[fan = "in"]').length).toBe(inbound.length)
      expect(cy.edges('[onPath = 1][fan]').length).toBe(0)
      cy.destroy()
    }
  })

  it('writes no text on other text: not with 50 payers open, nor in any recorded case', () => {
    const pictures = [closed(), open(), ...everyCase().flatMap((c) => [toElements(buildFlow(c)), toElements(buildFlow(c, { collapse: true }))])]
    for (const elements of pictures) {
      const { fixed, labels } = textBoxes(elements)
      const written = [...labels.values()]
      for (const [i, a] of written.entries()) {
        expect(fixed.some((b) => overlap(a, b))).toBe(false)
        expect(written.slice(i + 1).some((b) => overlap(a, b))).toBe(false)
      }
    }
  })

  it('keeps the amount on the Hop Rail path of every recorded case', () => {
    for (const c of everyCase()) {
      const path = toElements(buildFlow(c)).filter((e) => e.group === 'edges' && e.data.onPath)
      expect(path.every((e) => e.data.label), c.id).toBe(true)
    }
  })

  it('keeps every payer of an opened fan off the line the money comes in along, and off each other', () => {
    const tiles = open().filter((e) => e.group === 'nodes' && !e.data.owner)
    const places = new Set(tiles.map((e) => `${e.position!.x}:${e.position!.y}`))
    expect(places.size).toBe(tiles.length)
    expect(tiles.filter((e) => e.position!.x < 0).every((e) => e.position!.y !== 0)).toBe(true)
  })
})
