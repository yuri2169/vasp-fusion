import { createContext, useContext } from 'react'
import type { Chain } from '../api/models'

/** `CaseDetail.tx_chains`: the chain of every transaction of the case in view that is not on
 *  the case's own chain (a bridge's payout, and the transfers after it). A transaction link
 *  looks its hash up here, so it opens the right explorer wherever it is drawn. */
export const TxChains = createContext<Readonly<Record<string, Chain>>>({})

export function useTxChain(hash: string, fallback: Chain): Chain {
  return useContext(TxChains)[hash] ?? fallback
}
