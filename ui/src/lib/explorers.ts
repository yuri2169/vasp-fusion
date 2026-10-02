import type { Chain } from '../api/models'

/** Public block explorers, for the officer to check a wallet or a transfer independently.
 *  They open in a new tab and need the internet; nothing in the app depends on them. */
const EXPLORERS: Record<Chain, { address: string; tx: string; hexPrefix?: boolean }> = {
  tron: { address: 'https://tronscan.org/#/address/', tx: 'https://tronscan.org/#/transaction/' },
  ethereum: { address: 'https://etherscan.io/address/', tx: 'https://etherscan.io/tx/', hexPrefix: true },
  bsc: { address: 'https://bscscan.com/address/', tx: 'https://bscscan.com/tx/', hexPrefix: true },
  polygon: { address: 'https://polygonscan.com/address/', tx: 'https://polygonscan.com/tx/', hexPrefix: true },
  arbitrum: { address: 'https://arbiscan.io/address/', tx: 'https://arbiscan.io/tx/', hexPrefix: true },
  base: { address: 'https://basescan.org/address/', tx: 'https://basescan.org/tx/', hexPrefix: true },
  optimism: { address: 'https://optimistic.etherscan.io/address/', tx: 'https://optimistic.etherscan.io/tx/', hexPrefix: true },
  avalanche: { address: 'https://snowtrace.io/address/', tx: 'https://snowtrace.io/tx/', hexPrefix: true },
  // The explorer the Bitcoin adapter reads from (B5).
  bitcoin: { address: 'https://blockstream.info/address/', tx: 'https://blockstream.info/tx/' },
  solana: { address: 'https://solscan.io/account/', tx: 'https://solscan.io/tx/' },
}

export function addressUrl(chain: Chain, address: string): string {
  return EXPLORERS[chain].address + address
}

export function txUrl(chain: Chain, hash: string): string {
  const e = EXPLORERS[chain]
  return e.tx + (e.hexPrefix && !hash.startsWith('0x') ? `0x${hash}` : hash)
}

export function explorerName(chain: Chain): string {
  return new URL(EXPLORERS[chain].address).hostname.replace(/^www\./, '')
}
