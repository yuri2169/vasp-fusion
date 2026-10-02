import { describe, expect, it } from 'vitest'
import type { CaseDetail } from '../api/models'
import { MOCK_CASES, REAL_CASES, readCase, readMock } from '../test/files'
import { timelineOf } from './timeline'

const hero = readCase<CaseDetail>('tron-coindcx')
const okx = readMock<CaseDetail>('cases/demo-tron-okx.json')
const events = (c: CaseDetail) => timelineOf(c).days.flatMap((d) => d.events)

describe('timelineOf', () => {
  it('lists every transfer once, oldest first', () => {
    const all = events(hero)
    expect(all).toHaveLength(hero.graph.edges.length)
    expect(all.map((e) => e.at)).toEqual([...all.map((e) => e.at)].sort())
  })

  it('groups the transfers by UTC day and says when days passed in between', () => {
    const { days } = timelineOf(hero)
    expect(days.map((d) => d.date)).toEqual(['2025-05-23', '2025-05-25', '2025-07-04', '2025-07-14'])
    expect(days.map((d) => d.gapDays)).toEqual([null, 2, 40, 10])
    expect(days.map((d) => d.events.length)).toEqual([3, 1, 1, 3])
  })

  it('says whether money was received, sent by the wallet, or forwarded by a later wallet', () => {
    expect(events(hero).map((e) => e.kind)).toEqual(['received', 'received', 'received', 'sent', 'received', 'received', 'sent', 'forwarded'])
    expect(events(okx).map((e) => e.kind)).toEqual(['sent', 'forwarded', 'forwarded', 'forwarded', 'forwarded', 'forwarded', 'forwarded'])
  })

  it('times a forward from the last arrival at the wallet that forwarded', () => {
    const forwarded = events(hero).at(-1)!
    expect([forwarded.from.slice(0, 6), forwarded.to.slice(0, 6)]).toEqual(['TDYCQE', 'TDqSqu'])
    expect(forwarded.afterArrivalS).toBe(11 * 60 + 57) // 16:00:51 → 16:12:48
    // the wallet's own first payment came 32 h after it was last funded
    const sent = events(hero).find((e) => e.kind === 'sent')!
    expect(sent.afterArrivalS).toBe(Date.parse('2025-05-25T03:22:15Z') / 1000 - Date.parse('2025-05-23T19:02:48Z') / 1000)
    // nothing arrived before the first transfer of the mock case
    expect(events(okx)[0].afterArrivalS).toBeNull()
  })

  it('carries the traced part and the on-chain amount of each transfer', () => {
    const first = events(hero)[0]
    expect([first.amount, first.onChain, first.asset]).toEqual([14, 14, 'USDT'])
    expect(first.txHash).toHaveLength(64)
  })

  it('puts a pattern on the first transfer it cites, and keeps the rest apart', () => {
    const { days, unplaced } = timelineOf(hero)
    const flagged = days.flatMap((d) => d.events).filter((e) => e.flags.length > 0)
    expect(flagged).toHaveLength(1)
    expect(flagged[0].flags[0].code).toBe('deposit_like')
    expect(flagged[0].to.slice(0, 6)).toBe('TDYCQE')
    expect(unplaced).toEqual([])

    const noHash = timelineOf({ ...hero, typology_flags: [{ ...hero.typology_flags[0], tx_hashes: ['not-in-this-case'] }] })
    expect(noHash.unplaced).toHaveLength(1)
    expect(noHash.days.flatMap((d) => d.events).every((e) => e.flags.length === 0)).toBe(true)
  })

  it('never loses or repeats a pattern, in any case', () => {
    for (const c of [...MOCK_CASES.map((id) => readMock<CaseDetail>(`cases/${id}.json`)), ...REAL_CASES.map((id) => readCase<CaseDetail>(id))]) {
      const { days, unplaced } = timelineOf(c)
      const placed = days.flatMap((d) => d.events).flatMap((e) => e.flags)
      expect(placed.length + unplaced.length, c.id).toBe(c.typology_flags.length)
    }
  })

  it('is empty for a case with no transfers', () => {
    expect(timelineOf({ ...hero, graph: { nodes: [], edges: [] }, typology_flags: [] })).toEqual({ days: [], unplaced: [] })
  })
})
