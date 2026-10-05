import type { Chain } from '../api/models'

export type ChainFamily = 'tron' | 'evm' | 'bitcoin' | 'solana'

export interface ChainInfo {
  /** What the badge prints. */
  code: string
  name: string
  family: ChainFamily
  /** Whether POST /api/cases accepts it today (docs/api_contract.md). */
  traceable: boolean
  /** One sentence for the officer when it is not. */
  whyNot?: string
}

export const CHAINS: Record<Chain, ChainInfo> = {
  tron: { code: 'TRON', name: 'Tron', family: 'tron', traceable: true },
  ethereum: { code: 'ETH', name: 'Ethereum', family: 'evm', traceable: true },
  polygon: { code: 'POLYGON', name: 'Polygon', family: 'evm', traceable: true },
  arbitrum: { code: 'ARB', name: 'Arbitrum', family: 'evm', traceable: true },
  base: { code: 'BASE', name: 'Base', family: 'evm', traceable: true },
  optimism: { code: 'OP', name: 'Optimism', family: 'evm', traceable: true },
  bsc: { code: 'BNB', name: 'BNB Chain', family: 'evm', traceable: true },
  avalanche: {
    code: 'AVAX',
    name: 'Avalanche',
    family: 'evm',
    traceable: false,
    whyNot: 'Avalanche wallets cannot be traced yet.',
  },
  bitcoin: { code: 'BTC', name: 'Bitcoin', family: 'bitcoin', traceable: true },
  solana: { code: 'SOL', name: 'Solana', family: 'solana', traceable: true },
}

/** The chains an 0x… address can be traced on; the search bar offers these. Ethereum first: it is the default. */
export const EVM_TRACEABLE: Chain[] = ['ethereum', 'bsc', 'polygon', 'arbitrum', 'base', 'optimism']

/** A wallet's id in a case's graph. It is the address, except for a wallet the money reached
 *  on another chain than the case (over a bridge): that one is `chain:address`, because an EVM
 *  address is the same string on every EVM chain (docs/api_contract.md, "Money that crossed a
 *  bridge"). */
export function walletId(home: Chain, address: string, chain?: Chain | null): string {
  return !chain || chain === home ? address : `${chain}:${address}`
}

/** The chain and plain address of a wallet id. No address format here contains a colon. */
export function splitWalletId(id: string, home: Chain): { chain: Chain; address: string; away: boolean } {
  const at = id.indexOf(':')
  const chain = at > 0 ? id.slice(0, at) : ''
  return chain in CHAINS ? { chain: chain as Chain, address: id.slice(at + 1), away: true } : { chain: home, address: id, away: false }
}
