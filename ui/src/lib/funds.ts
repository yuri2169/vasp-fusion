/** Words and fills for "where the funds went" (CaseDetail.where_funds_went). */
import type { FundsSlice } from '../api/models'

/** What a slice is, in the officer's words. The trace's own sentences use the same ones. */
export function fundsName(slice: FundsSlice): string {
  const name = slice.name
  switch (slice.kind) {
    case 'vasp':
      return name ?? 'An exchange'
    case 'sanctioned':
      return `${name ?? 'A sanctioned address'} (sanctioned)`
    case 'mixer':
      return `${name ?? 'A mixer'} (mixer)`
    case 'bridge':
      return `${name ?? 'A bridge'} (bridge)`
    case 'other_label':
      return name ?? 'Another labelled party'
    case 'hub':
      return 'Busy unlabelled wallets'
    case 'beyond_hop_limit':
      return 'Past the hop limit'
    case 'not_moved':
      return 'Has not moved on'
    case 'not_followed':
      return 'Not followed'
    case 'returned':
      return 'Came back to the wallet'
    case 'fee':
      return 'Network fees'
  }
}

/** Kind is not told by hue (the six brand colours are not a categorical palette). Three
 *  fills, each a status with words beside it, and one hatch for everything unresolved:
 *    named  saffron: the exchange the case names
 *    party  ink: any other named party (an exchange not named, a bridge, a contract)
 *    seal   red: sanctioned or mixer
 *    open   hatched: where the trail stops without a name */
export type FundsFill = 'named' | 'party' | 'seal' | 'open'

export function fundsFill(slice: FundsSlice, named?: string | null): FundsFill {
  if (slice.kind === 'sanctioned' || slice.kind === 'mixer') return 'seal'
  if (slice.kind === 'vasp') return named && slice.name === named ? 'named' : 'party'
  if (slice.kind === 'bridge' || slice.kind === 'other_label') return 'party'
  return 'open'
}
