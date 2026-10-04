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
        'inline-flex shrink-0 items-center border font-mono text-2xs font-medium tracking-wide',
        size === 'sm' ? 'h-[18px] px-1' : 'h-5 px-1.5',
        tentative ? 'border-dashed border-rule text-ink-dim' : 'border-rule bg-surface text-chain',
      )}
    >
      {code}
    </span>
  )
}
