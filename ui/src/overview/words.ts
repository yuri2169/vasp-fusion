/** Words and figures shared by the dashboard, the labels explorer, the model page and the watchlist. */
import type { Category, Chain } from '../api/models'
import { CHAINS } from '../lib/chains'

export const isChain = (chain: string): chain is Chain => chain in CHAINS

/** A chain's name as the officer knows it; a chain the tool cannot trace keeps the label store's spelling, capitalised. */
export const chainName = (chain: string) =>
  isChain(chain) ? CHAINS[chain].name : chain === 'evm' ? 'Any EVM chain' : chain.replace(/(^|-)([a-z])/g, (_, dash: string, c: string) => (dash ? ' ' : '') + c.toUpperCase())

export const CATEGORY_NAMES: Record<Category, string> = {
  exchange: 'Exchange',
  custodial_wallet: 'Custodial wallet',
  swap_service: 'Swap service',
  bridge: 'Bridge',
  mixer: 'Mixer',
  sanctioned: 'Sanctioned',
  scam: 'Scam',
  defi: 'DeFi contract',
  entity: 'Other named party',
}
export const categoryName = (c: string) => CATEGORY_NAMES[c as Category] ?? c

export const count = (n: number) => n.toLocaleString('en-US')
export const plural = (n: number, word: string, many = `${word}s`) => `${count(n)} ${n === 1 ? word : many}`

/** A share as a figure on an axis or in a table: 98.6%, and never rounded up to 100%. */
export const share = (v: number) => (v >= 1 ? '100%' : v >= 0.9995 ? 'over 99.9%' : `${(v * 100).toFixed(1)}%`)

/** A score between 0 and 1 to three places, never written as a perfect 1.000. */
export const score = (v: number | null | undefined) => (v == null ? 'not measured' : v >= 0.9995 ? 'over 0.999' : v.toFixed(3))
