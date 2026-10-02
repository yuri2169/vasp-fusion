import { cx } from '../lib/cx'
import { formatNumber, formatUsd } from '../lib/format'

const DOLLAR_STABLECOINS = new Set(['USDT', 'USDC', 'DAI', 'TUSD', 'USDD', 'BUSD', 'FDUSD'])

const SIZE = { sm: 'text-xs', md: 'text-sm', lg: 'text-lg' }

/** An amount in its own asset, in mono with tabular figures, with the US dollar value
 *  after it when there is one and it says something the amount does not. */
export function Amount({
  value,
  asset,
  usd,
  size = 'md',
  className,
}: {
  value: number
  asset: string
  usd?: number | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  const showUsd = usd != null && !(DOLLAR_STABLECOINS.has(asset.toUpperCase()) && Math.abs(usd - value) < 0.005)
  return (
    <span className={cx('tabular whitespace-nowrap font-mono', SIZE[size], className)}>
      <span className="font-medium">{formatNumber(value)}</span> <span className="text-muted">{asset}</span>
      {showUsd && <span className="ml-2 text-muted">{formatUsd(usd)}</span>}
    </span>
  )
}
