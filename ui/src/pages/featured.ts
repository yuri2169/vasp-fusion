import type { CaseSummary } from '../api/models'

export interface FeaturedCases {
  named: CaseSummary[]
  notNamed: CaseSummary[]
  /** Recorded cases whose address comes from a publicly documented incident: shown on their
   *  own, with their sources, and never in the two groups below. */
  documented: CaseSummary[]
}

const byRef = (a: CaseSummary, b: CaseSummary) => (a.case_ref ?? a.id).localeCompare(b.case_ref ?? b.id, 'en', { numeric: true })

/** Which recorded wallets the landing offers, and in what order. Nothing is picked by name:
 *  the groups come from each case's own outcome.
 *  - Named an exchange: one per chain, so every chain with a recorded answer shows; with
 *    fewer than four chains the rest follow in case-reference order, up to four.
 *  - Did not name one: one per outcome, "insufficient evidence" before "sanctioned or mixer".
 *  - Documented: every recorded case that carries a `documented` block, whatever its outcome. */
export function featuredCases(cases: CaseSummary[]): FeaturedCases {
  const recorded = cases.filter((c) => c.demo && c.outcome != null).sort(byRef)
  const documented = recorded.filter((c) => c.documented)
  const done = recorded.filter((c) => !c.documented)
  const attributed = done.filter((c) => c.outcome === 'ATTRIBUTED')
  const firstOfChain = attributed.filter((c, i) => attributed.findIndex((o) => o.chain === c.chain) === i)
  const named = firstOfChain.length >= 4 ? firstOfChain : [...firstOfChain, ...attributed.filter((c) => !firstOfChain.includes(c))].slice(0, 4)

  const rest = done.filter((c) => c.outcome !== 'ATTRIBUTED')
  const notNamed = rest
    .filter((c, i) => rest.findIndex((o) => o.outcome === c.outcome) === i)
    .sort((a, b) => Number(b.outcome === 'INSUFFICIENT_EVIDENCE') - Number(a.outcome === 'INSUFFICIENT_EVIDENCE'))
  return { named, notNamed, documented }
}
