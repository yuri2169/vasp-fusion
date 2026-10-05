import { ExternalLink } from 'lucide-react'
import type { Chain } from '../api/models'
import { cx } from '../lib/cx'
import { explorerName, txUrl } from '../lib/explorers'
import { truncateMiddle } from '../lib/format'
import { useTxChain } from '../lib/txChains'
import { CopyButton } from './CopyButton'
import { Tip, useTip } from './Tip'

/** A transaction hash: mono, shortened in the middle, whole on hover or focus, copied whole. */
export function TxHash({ hash, chain: given, full, className }: { hash: string; chain: Chain; full?: boolean; className?: string }) {
  const tip = useTip()
  // a transaction after a bridge is on another chain than the case: the case says which
  const chain = useTxChain(hash, given)
  return (
    <span
      role="group"
      aria-label={`Transaction ${hash}`}
      {...tip.bind}
      className={cx('inline-flex max-w-full items-center gap-0.5 align-middle text-sm', className)}
    >
      <span className={cx('font-mono text-fg', full && 'break-all')}>{full ? hash : truncateMiddle(hash)}</span>
      <span className="flex shrink-0 items-center">
        <CopyButton value={hash} label="transaction hash" />
        <a
          href={txUrl(chain, hash)}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open on ${explorerName(chain)} (new tab)`}
          title={`Open on ${explorerName(chain)}`}
          className="inline-flex h-5 w-5 items-center justify-center text-ink-dim hover:bg-surface-3 hover:text-ink"
        >
          <ExternalLink size={13} aria-hidden />
        </a>
      </span>
      {!full && (
        <Tip id={tip.id} anchor={tip.anchor}>
          <span className="block break-all font-mono">{hash}</span>
          <span className="mt-1 block text-muted">Transaction hash</span>
        </Tip>
      )}
    </span>
  )
}
