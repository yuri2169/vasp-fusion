import type { Chain } from '../api/models'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'

/** The chain, as a short code in mono. `tentative` is a guess made while the officer is still typing. */
export function ChainBadge({ chain, tentative = false, size = 'md' }: { chain: Chain; tentative?: boolean; size?: 'sm' | 'md' }) {
  const { code, name } = CHAINS[chain]
  return (
    <span
      title={tentative ? `Looks like ${name}` : name}
      className={cx(
        'inline-flex shrink-0 items-center rounded-sm border font-mono text-xs font-medium tracking-wide',
        size === 'sm' ? 'h-5 px-1' : 'h-6 px-1.5',
        tentative ? 'border-dashed border-rule-strong text-muted' : 'border-rule-strong bg-surface text-fg',
      )}
    >
      {code}
    </span>
  )
}
