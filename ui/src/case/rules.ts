/** The few rules of the backend the case page has to know to offer the right action. */
import type { Candidate, CaseDetail, TypologyFlag } from '../api/models'

/** The bar a candidate must clear to be named (docs/api_contract.md; checked on a label hold-out in B7, not calibrated). */
export const NAMING_BAR = 0.6

/** `POST /api/cases` takes 1 to 5 hops out; 3 when the officer does not say. */
export const HOP_LIMITS = [1, 2, 3, 4, 5]
export const DEFAULT_HOPS = 3

/** A lead from the deposit-address model: something to look into, never part of the answer. */
export const isLead = (flag: TypologyFlag) => flag.code === 'deposit_like'
export const leadsOf = (c: CaseDetail) => c.typology_flags.filter(isLead)

/** The exchange funded the wallet; the wallet's money did not go there. */
export const isInbound = (x: Candidate) => x.direction === 'inbound'

/** Whether a request can be drafted to this exchange from this case (the desk's own rule, B8). */
export const routable = (x: Candidate) =>
  !isInbound(x) && x.hops >= 1 && x.confidence >= NAMING_BAR && x.vasp !== 'Unidentified exchange'

export const deskLink = (c: CaseDetail, vasp: string) => `/desk?vasp=${encodeURIComponent(vasp)}&case=${encodeURIComponent(c.id)}`
