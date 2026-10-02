import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { MOCK_CASES, REAL_CASES, readCase, readMock } from '../test/files'
import { toGraphML } from './graphml'

const hero = readCase<CaseDetail>('tron-coindcx')
const parse = (xml: string) => new DOMParser().parseFromString(xml, 'application/xml')
const data = (el: Element, key: string) => [...el.children].find((d) => d.getAttribute('key') === key)?.textContent

describe('toGraphML', () => {
  it('is well-formed XML for every case', () => {
    for (const c of [...MOCK_CASES.map((id) => readMock<CaseDetail>(`cases/${id}.json`)), ...REAL_CASES.map((id) => readCase<CaseDetail>(id))]) {
      const doc = parse(toGraphML(c))
      expect(doc.querySelector('parsererror'), c.id).toBeNull()
      expect(doc.documentElement.localName).toBe('graphml')
    }
  })

  it('has one node per wallet and one edge per transfer, with whole addresses and hashes', () => {
    const doc = parse(toGraphML(hero))
    const nodes = [...doc.querySelectorAll('node')]
    const edges = [...doc.querySelectorAll('edge')]
    expect(nodes.map((n) => n.getAttribute('id'))).toEqual(hero.graph.nodes.map((n) => n.id))
    expect(edges).toHaveLength(hero.graph.edges.length)
    const first = hero.graph.edges[0]
    expect([edges[0].getAttribute('source'), edges[0].getAttribute('target')]).toEqual([first.source, first.target])
    expect(data(edges[0], 'tx_hash')).toBe(first.tx_hash)
    expect(data(edges[0], 'amount')).toBe('1530')
    expect(data(edges[0], 'block_time')).toBe(first.block_time)
    expect(doc.querySelector('graph')!.getAttribute('edgedefault')).toBe('directed')
  })

  it('carries the role and the label of a wallet', () => {
    const doc = parse(toGraphML(hero))
    const deposit = [...doc.querySelectorAll('node')].find((n) => n.getAttribute('id')!.startsWith('TCw8j3'))!
    expect(data(deposit, 'role')).toBe('exchange_deposit')
    expect(data(deposit, 'entity')).toBe('CoinDCX')
    expect(data(deposit, 'tier')).toBe('derived')
    const suspect = doc.querySelector('node')!
    expect(data(suspect, 'role')).toBe('suspect')
    expect(data(suspect, 'entity')).toBeUndefined()
  })

  it('declares every data key it uses', () => {
    const doc = parse(toGraphML(hero))
    const declared = new Set([...doc.querySelectorAll('key')].map((k) => k.getAttribute('id')))
    for (const d of doc.querySelectorAll('data')) expect(declared.has(d.getAttribute('key'))).toBe(true)
  })

  it('says which case it is', () => {
    const graph = parse(toGraphML(hero)).querySelector('graph')!
    expect(data(graph, 'case_id')).toBe('tron-coindcx')
    expect(data(graph, 'wallet')).toBe(hero.address)
    expect(data(graph, 'outcome')).toBe('ATTRIBUTED')
    expect(data(graph, 'findings_sha256')).toBe(hero.provenance.findings_sha256)
  })

  it('escapes what XML reserves', () => {
    const odd: CaseDetail = {
      ...hero,
      graph: {
        nodes: hero.graph.nodes.map((n, i) => (i === 1 && n.label ? { ...n, label: { ...n.label, entity: 'A & B <"Exchange">' } } : n)),
        edges: hero.graph.edges,
      },
    }
    const xml = toGraphML(odd)
    expect(xml).toContain('A &amp; B &lt;&quot;Exchange&quot;&gt;')
    expect(parse(xml).querySelector('parsererror')).toBeNull()
  })
})
