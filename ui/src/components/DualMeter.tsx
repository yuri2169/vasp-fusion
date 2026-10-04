import { cx } from '../lib/cx'
import { formatConfidence, formatConfidenceRange, formatDuration, formatPercent } from '../lib/format'

export interface DualMeterProps {
  /** 1 = nearest (hops, then share of the funds, then time). */
  proximityRank: number
  hops: number
  shareOfFunds: number
  timeToReachS?: number | null
  confidence: number
  /** Present when the label behind the candidate was scored by the model; absent = rule confidence. */
  interval?: [number, number] | number[] | null
  /** The bar a candidate must clear to be named. */
  bar?: number
  layout?: 'row' | 'stack'
  className?: string
}

const MAX_HOPS = 5
const pct = (v: number) => `${Math.round(Math.max(0, Math.min(1, v)) * 100)}%`
const hopWords = (n: number) => (n === 0 ? 'The wallet itself' : `${n} hop${n === 1 ? '' : 's'}`)

/** Proximity and confidence, side by side and never merged: how near an exchange is to the
 *  wallet, and how sure we are that it is that exchange. They are drawn in two different
 *  forms (a short rail of hops, a bar with a threshold) so they cannot be read as one score. */
export function DualMeter({
  proximityRank,
  hops,
  shareOfFunds,
  timeToReachS,
  confidence,
  interval,
  bar = 0.6,
  layout = 'row',
  className,
}: DualMeterProps) {
  const range = interval && interval.length === 2 ? ([interval[0], interval[1]] as const) : null
  const clears = confidence >= bar
  const barText = `${clears ? 'at or above' : 'under'} the ${bar.toFixed(2)} bar`
  const proximityFacts = [
    hopWords(hops),
    `${formatPercent(shareOfFunds)} of the funds`,
    timeToReachS != null && timeToReachS > 0 ? formatDuration(timeToReachS) : null,
  ].filter(Boolean) as string[]
  const confidenceText = [
    `${range ? 'confidence' : 'rule confidence'} ${formatConfidence(confidence)}`,
    range && formatConfidenceRange(range[0], range[1]),
    barText,
  ]
    .filter(Boolean)
    .join(', ')

  return (
    <div className={cx('grid gap-x-6 gap-y-4', layout === 'row' ? 'grid-cols-2' : 'grid-cols-1', className)}>
      {/* --- proximity: a short rail of hops ---------------------------------- */}
      <div
        role="meter"
        aria-label="Proximity"
        aria-valuemin={0}
        aria-valuemax={MAX_HOPS}
        aria-valuenow={hops}
        aria-valuetext={`Rank ${proximityRank}: ${proximityFacts.join(', ')}`}
        className="flex min-w-0 flex-col gap-1.5"
      >
        <div className="flex h-5 items-center justify-between gap-2">
          <span className="eyebrow">Proximity</span>
          <span className="tabular font-mono text-sm text-muted">rank {proximityRank}</span>
        </div>
        <div aria-hidden className="flex h-5 items-center">
          <span className="h-2 w-2 shrink-0 border border-ink bg-surface" />
          {Array.from({ length: Math.max(MAX_HOPS, hops) }, (_, i) => (
            <span key={i} className="flex flex-1 items-center">
              <span className={cx('h-0 flex-1 border-t', i < hops ? 'border-fusion' : 'border-dashed border-rule')} />
              <span
                className={cx(
                  'shrink-0',
                  i === hops - 1 ? 'h-2.5 w-2.5 bg-fusion' : i < hops ? 'h-1.5 w-1.5 bg-fusion' : 'h-1 w-1 bg-rule',
                )}
              />
            </span>
          ))}
        </div>
        <div className="flex flex-wrap gap-x-2 text-sm text-fg">
          {proximityFacts.map((fact, i) => (
            <span key={fact} className={cx('whitespace-nowrap', i > 0 && 'text-muted')}>
              {fact}
            </span>
          ))}
        </div>
      </div>

      {/* --- confidence: a bar with the naming threshold marked ---------------- */}
      <div
        role="meter"
        aria-label="Confidence"
        aria-valuemin={0}
        aria-valuemax={1}
        aria-valuenow={Number(confidence.toFixed(2))}
        aria-valuetext={confidenceText}
        className="flex min-w-0 flex-col gap-1.5"
      >
        <div className="flex h-5 items-center justify-between gap-2">
          <span className="eyebrow">{range ? 'Confidence' : 'Rule confidence'}</span>
          <span className="tabular font-mono text-base font-semibold text-fg">{formatConfidence(confidence)}</span>
        </div>
        <div aria-hidden className="relative flex h-5 items-center">
          <div className="relative h-2 w-full bg-surface-3">
            {range && (
              <span
                data-testid="confidence-range"
                className="absolute inset-y-0 bg-fusion opacity-30"
                style={{ left: pct(range[0]), width: `${Math.round((range[1] - range[0]) * 100)}%` }}
              />
            )}
            <span
              data-testid="confidence-fill"
              className={cx('anim-bar absolute inset-y-0 left-0', clears ? 'bg-fusion' : 'hatch')}
              style={{ width: pct(confidence) }}
            />
          </div>
          <span data-testid="confidence-bar-mark" className="absolute inset-y-0 w-0 border-l-2 border-ink" style={{ left: pct(bar) }} />
        </div>
        <div className="flex flex-wrap justify-between gap-x-2 text-sm">
          <span className={cx('whitespace-nowrap', clears ? 'text-fg' : 'font-medium text-fg')}>
            {clears ? `At or above the ${bar.toFixed(2)} bar` : `Under the ${bar.toFixed(2)} bar`}
          </span>
          {range && <span className="tabular whitespace-nowrap font-mono text-muted">{formatConfidenceRange(range[0], range[1])}</span>}
        </div>
      </div>
    </div>
  )
}
