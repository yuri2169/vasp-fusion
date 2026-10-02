import { ExternalLink } from 'lucide-react'
import { Link } from 'react-router'
import type { Chain, Tier } from '../api/models'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { addressUrl, explorerName } from '../lib/explorers'
import { truncateMiddle } from '../lib/format'
import { CopyButton } from './CopyButton'
import { TierIcon, TIERS } from './TierTag'
import { Tip, useTip } from './Tip'

export interface AddressChipProps {
  address: string
  chain: Chain
  /** The owner a label names, with the label's tier. Leave both out for an unlabelled address. */
  entity?: string | null
  tier?: Tier | null
  /** Marks the wallet the case is about. */
  role?: 'suspect'
  /** Print the address whole (letters, tables of record). */
  full?: boolean
  head?: number
  tail?: number
  /** A page in the app for this address; the address text becomes a link to it. */
  to?: string
  /** 'copy' leaves out the explorer link, where room is tight (the Hop Rail). */
  actions?: 'all' | 'copy'
  className?: string
}

/** An address, the core content of this tool: mono, shortened in the middle, with the
 *  whole of it one hover, one Tab or one click (copy) away. Copy always copies it whole. */
export function AddressChip({ address, chain, entity, tier, role, full, head = 6, tail = 6, to, actions = 'all', className }: AddressChipProps) {
  const tip = useTip()
  const shown = full ? address : truncateMiddle(address, head, tail)
  const tierName = entity ? TIERS[tier ?? 'none'].name : null
  const name = [`${CHAINS[chain].name} address ${address}`, entity, tierName].filter(Boolean).join(', ')

  return (
    <span
      role="group"
      aria-label={name}
      {...tip.bind}
      className={cx(
        'inline-flex h-7 max-w-full items-center gap-1.5 rounded border border-rule bg-surface pl-2 pr-0.5 align-middle text-xs',
        className,
      )}
    >
      {role === 'suspect' && (
        <span className="-ml-2 inline-flex self-stretch items-center rounded-l-sm bg-fg px-1.5 font-medium uppercase tracking-wide text-page">
          Suspect
        </span>
      )}
      {entity && (
        <span className="inline-flex min-w-0 items-center gap-1 font-semibold text-fg">
          <TierIcon tier={tier ?? null} />
          <span className="truncate">{entity}</span>
        </span>
      )}
      {to ? (
        <Link to={to} className="font-mono text-fg underline decoration-rule-strong underline-offset-2 hover:decoration-fg">
          {shown}
        </Link>
      ) : (
        <span className={cx('font-mono text-fg', full && 'break-all')}>{shown}</span>
      )}
      <span className="flex shrink-0 items-center">
        <CopyButton value={address} label="address" />
        {actions === 'all' && <a
          href={addressUrl(chain, address)}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`Open on ${explorerName(chain)} (new tab)`}
          title={`Open on ${explorerName(chain)}`}
          className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-muted hover:bg-sunk hover:text-fg"
        >
          <ExternalLink size={13} aria-hidden />
        </a>}
      </span>
      <Tip id={tip.id} anchor={tip.anchor}>
        <span className="block break-all font-mono">{address}</span>
        <span className="mt-1 flex flex-wrap items-center gap-x-1.5 text-muted">
          {CHAINS[chain].name}
          {entity && (
            <>
              <span aria-hidden>·</span>
              <span className="font-medium text-fg">{entity}</span>
              <span aria-hidden>·</span>
              {tierName}
            </>
          )}
          {!entity && (
            <>
              <span aria-hidden>·</span>
              {TIERS.none.name}
            </>
          )}
        </span>
      </Tip>
    </span>
  )
}
