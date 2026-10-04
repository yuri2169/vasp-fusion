import type { CaseSummary } from '../api/models'

export interface FeaturedCases {
  named: CaseSummary[]
  notNamed: CaseSummary[]
}

const byRef = (a: CaseSummary, b: CaseSummary) => (a.case_ref ?? a.id).localeCompare(b.case_ref ?? b.id, 'en', { numeric: true })

/** Which recorded wallets the landing offers, and in what order. Nothing is picked by name:
 *  the groups come from each case's own outcome.
 *  - Named an exchange: up to four, one per chain first (so every traceable chain shows),
 *    then the rest in case-reference order.
 *  - Did not name one: one per outcome, "insufficient evidence" before "sanctioned or mixer". */
export function featuredCases(cases: CaseSummary[]): FeaturedCases {
  const done = cases.filter((c) => c.demo && c.outcome != null).sort(byRef)
  const attributed = done.filter((c) => c.outcome === 'ATTRIBUTED')
  const firstOfChain = attributed.filter((c, i) => attributed.findIndex((o) => o.chain === c.chain) === i)
  const named = [...firstOfChain, ...attributed.filter((c) => !firstOfChain.includes(c))].slice(0, 4)

  const rest = done.filter((c) => c.outcome !== 'ATTRIBUTED')
  const notNamed = rest
    .filter((c, i) => rest.findIndex((o) => o.outcome === c.outcome) === i)
    .sort((a, b) => Number(b.outcome === 'INSUFFICIENT_EVIDENCE') - Number(a.outcome === 'INSUFFICIENT_EVIDENCE'))
  return { named, notNamed }
}
