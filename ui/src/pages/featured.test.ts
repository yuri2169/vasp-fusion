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

describe('featuredCases', () => {
  it('shows six of the eight: four named (one per chain first), two that were not', () => {
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
})
