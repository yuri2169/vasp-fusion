import { describe, expect, it } from 'vitest'
import type { CaseSummary } from '../api/models'
import { featuredCases } from './featured'

const c = (ref: number, chain: string, outcome: string | null, demo = true): CaseSummary =>
  ({ id: `c${ref}`, case_ref: `DEMO/2026/${ref}`, chain, outcome, demo, address: `a${ref}`, status: outcome ? 'done' : 'running', created_at: '2026-10-01T00:00:00Z' }) as unknown as CaseSummary

// The shape of demo/cases.json: eight recorded cases, four of which name an exchange.
const EIGHT = [
  c(108, 'bitcoin', 'ATTRIBUTED'),
  c(107, 'ethereum', 'INSUFFICIENT_EVIDENCE'),
  c(106, 'ethereum', 'INSUFFICIENT_EVIDENCE'),
  c(105, 'tron', 'INSUFFICIENT_EVIDENCE'),
  c(104, 'tron', 'ATTRIBUTED'),
  c(103, 'tron', 'SANCTIONED_OR_MIXER_REACHED'),
  c(102, 'ethereum', 'ATTRIBUTED'),
  c(101, 'tron', 'ATTRIBUTED'),
]
const refs = (list: CaseSummary[]) => list.map((x) => Number(x.case_ref!.split('/')[2]))

// demo/cases.json today: the eight, and one named case each on BNB Chain, Solana and Polygon.
const ELEVEN = [...EIGHT, c(109, 'bsc', 'ATTRIBUTED'), c(110, 'solana', 'ATTRIBUTED'), c(111, 'polygon', 'ATTRIBUTED')]

describe('featuredCases', () => {
  it('shows one named wallet for each of the six chains', () => {
    const f = featuredCases(ELEVEN)
    expect(refs(f.named)).toEqual([101, 102, 108, 109, 110, 111])
    expect(f.named.map((x) => x.chain)).toEqual(['tron', 'ethereum', 'bitcoin', 'bsc', 'solana', 'polygon'])
    expect(refs(f.notNamed)).toEqual([105, 103])
  })

  it('with three chains shows four named (one per chain first), and two that were not', () => {
    const f = featuredCases(EIGHT)
    expect(refs(f.named)).toEqual([101, 102, 108, 104])
    expect(refs(f.notNamed)).toEqual([105, 103])
  })

  it('groups by the outcome on the case, never by a list of names', () => {
    const f = featuredCases([c(1, 'tron', 'INSUFFICIENT_EVIDENCE'), c(2, 'tron', 'ATTRIBUTED')])
    expect(refs(f.named)).toEqual([2])
    expect(refs(f.notNamed)).toEqual([1])
  })

  it('leaves out cases that are not recorded or not finished', () => {
    const f = featuredCases([c(1, 'tron', 'ATTRIBUTED', false), c(2, 'tron', null)])
    expect(f.named).toEqual([])
    expect(f.notNamed).toEqual([])
  })

  it('keeps a documented case out of the two groups and offers it on its own', () => {
    const wazirx = { ...c(113, 'ethereum', 'INSUFFICIENT_EVIDENCE'), case_ref: 'DOC/2024/WAZIRX', documented: { title: 't', what_happened: 'w', statement: 's', sources: [] } } as CaseSummary
    const f = featuredCases([wazirx, ...ELEVEN])
    expect(f.documented).toEqual([wazirx])
    expect(f.named).not.toContain(wazirx)
    expect(f.notNamed).not.toContain(wazirx)
    expect(featuredCases(ELEVEN).documented).toEqual([])
  })
})
