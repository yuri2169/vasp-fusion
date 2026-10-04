import { createContext, useContext, type ReactNode } from 'react'
import type { FxRate } from '../api/models'
import { useFx } from '../api/queries'
import { formatInr } from '../lib/format'

/** The reference rate rupee amounts are shown at (GET /api/fx: config/fx.yaml). Null until
 *  it has been read, and where there is no rate: then no rupee amount is shown at all. */
const FxContext = createContext<FxRate | null>(null)

/** Reads the rate once for everything under it. */
export function FxProvider({ children }: { children: ReactNode }) {
  const fx = useFx()
  return <FxContext.Provider value={fx.data ?? null}>{children}</FxContext.Provider>
}

/** For a test or a story: a given rate, without the API. */
export function FxFixed({ rate, children }: { rate: FxRate | null; children: ReactNode }) {
  return <FxContext.Provider value={rate}>{children}</FxContext.Provider>
}

// eslint-disable-next-line react/only-export-components
export const useFxRate = () => useContext(FxContext)

/** Amounts in these assets are US dollars one for one (as the API counts `amount_usd`). */
const USD_ASSETS = new Set(['USDT', 'USDC'])

/** The US dollar value of an amount, when it has one: the value given, or the amount itself
 *  in a dollar stablecoin. */
// eslint-disable-next-line react/only-export-components
export const usdOf = (value: number, asset: string, usd?: number | null): number | null => usd ?? (USD_ASSETS.has(asset.toUpperCase()) ? value : null)

/** `(usd) => "₹1,46,559"`, or null while there is no rate. For text that is not an element. */
// eslint-disable-next-line react/only-export-components
export function useRupees(): (usd: number | null | undefined) => string | null {
  const fx = useFxRate()
  return (usd) => (fx && usd != null ? formatInr(usd * fx.rate) : null)
}

/** A US dollar amount in rupees at the reference rate, to sit beside the dollar figure. */
export function Rupees({ usd, className = 'ml-2 text-muted' }: { usd: number | null | undefined; className?: string }) {
  const text = useRupees()(usd)
  return text ? <span className={className}>{text}</span> : null
}

/** Which rate, whose, and of what date. Shown once per screen (the status bar) and under a letter. */
export function RupeeBasis({ className }: { className?: string }) {
  const fx = useFxRate()
  if (!fx) return null
  return (
    <span className={className} title={`${fx.source_title}. ${fx.source_publisher ?? ''}`.trim()}>
      {fx.basis}
    </span>
  )
}
