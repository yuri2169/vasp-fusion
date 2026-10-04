import type { FundsSlice } from '../api/models'
import { cx } from '../lib/cx'
import { formatAmount, formatPercent } from '../lib/format'
import { fundsFill, fundsName, type FundsFill } from '../lib/funds'
import { Tip, useTip } from './Tip'

const FILL: Record<FundsFill, string> = {
  named: 'bg-saffron',
  party: 'bg-chain',
  seal: 'bg-seal',
  open: 'hatch bg-surface-3',
}

function Segment({ slice, fill, asset }: { slice: FundsSlice; fill: FundsFill; asset: string }) {
  const tip = useTip()
  return (
    <span
      data-testid="funds-segment"
      data-fill={fill}
      onMouseEnter={tip.bind.onMouseEnter}
      onMouseLeave={tip.bind.onMouseLeave}
      style={{ flexBasis: `${(slice.share * 100).toFixed(1)}%` }}
      className={cx('anim-bar h-full min-w-[4px] shrink grow-0', FILL[fill])}
    >
      <Tip id={tip.id} anchor={tip.anchor}>
        <span className="block font-medium">{fundsName(slice)}</span>
        <span className="tabular mt-0.5 block font-mono text-muted">
          {formatPercent(slice.share)} · {formatAmount(slice.amount, asset)}
        </span>
      </Tip>
    </span>
  )
}

/** Where the money the wallet sent ended up: one bar, the whole of it, largest part first.
 *  Every part is named under the bar with its share and amount, so nothing rests on colour. */
export function FundsBar({
  slices,
  asset,
  total,
  named,
  className,
}: {
  slices?: FundsSlice[] | null
  asset: string
  total?: number | null
  /** The exchange the case names; its slice is the saffron one. */
  named?: string | null
  className?: string
}) {
  if (!slices || slices.length === 0) return null
  const summary = slices.map((s) => `${formatPercent(s.share)} ${fundsName(s)}`).join(', ')

  return (
    <div className={cx('flex flex-col gap-2', className)}>
      <p className="eyebrow">{total != null ? `Where the ${formatAmount(total, asset)} went` : 'Where the funds went'}</p>
      <div role="img" aria-label={summary} className="flex h-2.5 w-full gap-px">
        {slices.map((slice, i) => (
          <Segment key={slice.kind + (slice.name ?? '') + i} slice={slice} fill={fundsFill(slice, named)} asset={asset} />
        ))}
      </div>
      <ul aria-label="Where the funds went" className="flex flex-wrap gap-x-5 gap-y-1">
        {slices.map((slice, i) => (
          <li key={slice.kind + (slice.name ?? '') + i} className="flex items-center gap-1.5 text-sm">
            <span aria-hidden className={cx('h-2 w-2 shrink-0', FILL[fundsFill(slice, named)])} />
            <span className="font-medium text-fg">{fundsName(slice)}</span>
            <span className="tabular font-mono text-fg">{formatPercent(slice.share)}</span>
            <span className="tabular font-mono text-muted">{formatAmount(slice.amount, asset)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
