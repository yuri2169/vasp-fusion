import { Snowflake } from 'lucide-react'
import type { FreezeMark } from '../api/models'
import { cx } from '../lib/cx'
import { formatAmount } from '../lib/format'
import { AddressChip } from './AddressChip'
import { Tip, useTip } from './Tip'

/** What a freeze establishes, and what it does not (mirrors vaspfusion/labels/frozen.py, MEANING). */
export const FREEZE_MEANING =
  'The issuer put this address on the token’s blacklist on that date and had not taken it off when the list was read. It does not say why, and it says nothing about anyone who dealt with the address.'

/** An address the issuer of USDT has frozen. Drawn in the chain colour: the freeze is the token contract's own
 *  on-chain record, not a third party's list. Always the icon and the backend's words. */
export function FreezeChip({ mark, size = 'md' }: { mark: Pick<FreezeMark, 'text' | 'tx_hash' | 'contract' | 'frozen_asset'>; size?: 'sm' | 'md' }) {
  const tip = useTip()
  return (
    <>
      <span
        data-freeze
        tabIndex={0}
        aria-describedby={tip.open ? tip.id : undefined}
        {...tip.bind}
        className={cx(
          'inline-flex max-w-full shrink-0 items-center gap-1 border border-chain bg-chain-wash font-sans text-2xs font-semibold normal-case tracking-normal text-chain',
          size === 'sm' ? 'h-[18px] px-1.5' : 'h-5 px-2',
        )}
      >
        <Snowflake size={12} aria-hidden className="shrink-0" />
        <span className="whitespace-nowrap">{mark.text}</span>
      </span>
      <Tip id={tip.id} anchor={tip.anchor}>
        <span className="flex max-w-[44ch] flex-col gap-1">
          <span className="font-semibold">{mark.text} ({mark.frozen_asset})</span>
          <span>{FREEZE_MEANING}</span>
          <span className="text-ink-soft [overflow-wrap:anywhere]">Freezing transaction {mark.tx_hash}</span>
        </span>
      </Tip>
    </>
  )
}

const WHERE: Record<FreezeMark['where'], string> = {
  origin: 'This wallet',
  path: 'On the Hop Rail',
  graph: 'Elsewhere in the trace',
}

/** The case's wallets the issuer has frozen, under the case header. Says what a freeze does and does not mean. */
export function FreezeNote({ marks }: { marks: readonly FreezeMark[] | undefined }) {
  if (!marks?.length) return null
  const own = marks.find((m) => m.where === 'origin')
  return (
    <section aria-label="Frozen by the issuer of USDT" data-freezes={marks.length} className="flex flex-col gap-1.5 border-l-2 border-chain bg-chain-wash px-3 py-2">
      <span className="inline-flex flex-wrap items-center gap-2">
        <Snowflake size={15} aria-hidden className="shrink-0 text-chain" />
        <span className="text-2xs font-semibold uppercase tracking-[0.075em] text-chain">
          {own ? 'The issuer of USDT froze this wallet' : `${marks.length} wallet${marks.length === 1 ? '' : 's'} on this trace frozen by the issuer of USDT`}
        </span>
      </span>
      <ul className="flex flex-col gap-1">
        {marks.map((m) => (
          <li key={`${m.chain}:${m.address}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-base text-ink">
            <span className="colhead w-[19ch] shrink-0">{WHERE[m.where]}</span>
            {m.where !== 'origin' && <AddressChip address={m.id} chain={m.chain as never} />}
            <FreezeChip mark={m} size="sm" />
            {m.where !== 'origin' && m.amount > 0 && m.asset && (
              <span className="text-sm text-ink-soft">
                {formatAmount(m.amount, m.asset)} {m.side === 'inbound' ? 'paid in from it' : `reached it, ${m.hop} hop${m.hop === 1 ? '' : 's'} away`}
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="text-sm text-ink-soft">{FREEZE_MEANING}</p>
    </section>
  )
}
