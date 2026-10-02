import type { CaseStatus, Outcome } from '../api/models'
import { cx } from '../lib/cx'
import { formatConfidence, formatConfidenceRange } from '../lib/format'

export interface OutcomeStampProps {
  /** null while the case has no result yet; `status` then says why. */
  outcome: Outcome | null
  status?: CaseStatus
  /** The exchange named. For SANCTIONED_OR_MIXER_REACHED: the nearest exchange, if the rules kept one. */
  vasp?: string | null
  confidence?: number | null
  /** A range means the label behind the answer was scored by the model; none means rule confidence. */
  interval?: [number, number] | number[] | null
  /** INSUFFICIENT_EVIDENCE only: the first thing that would change the answer. */
  whatWouldChange?: string | null
  size?: 'sm' | 'lg'
  /** Set 1.5° off level, as a hand stamp lands. The Hop Rail's terminal stamp only. */
  tilt?: boolean
  className?: string
}

type Look = 'attributed' | 'insufficient' | 'sanctioned' | 'pending' | 'failed'

/** The three outcomes, each told apart by words, border and fill, not by colour alone:
 *  ATTRIBUTED solid saffron · INSUFFICIENT EVIDENCE slate, dashed · SANCTIONED / MIXER seal red. */
const LOOK: Record<Look, { word: string; box: string }> = {
  attributed: { word: 'Attributed', box: 'bg-saffron text-saffron-on' },
  insufficient: { word: 'Insufficient evidence', box: 'stamp-dashed bg-transparent text-muted' },
  sanctioned: { word: 'Sanctioned or mixer reached', box: 'bg-seal text-seal-on' },
  pending: { word: 'Tracing…', box: 'stamp-dashed bg-transparent text-muted' },
  failed: { word: 'Trace failed', box: 'bg-transparent text-seal-text' },
}

function lookOf(outcome: Outcome | null, status?: CaseStatus): Look {
  if (status === 'failed') return 'failed'
  if (!outcome || status === 'queued' || status === 'running') return 'pending'
  return outcome === 'ATTRIBUTED' ? 'attributed' : outcome === 'INSUFFICIENT_EVIDENCE' ? 'insufficient' : 'sanctioned'
}

/** "confidence 0.91" with its range under it, or "rule confidence 0.71" when the label was not scored by the model. */
function ConfidenceLines({ confidence, interval }: { confidence: number; interval?: number[] | null }) {
  const range = interval && interval.length === 2
  return (
    <span className="tabular flex flex-col font-mono text-xs leading-4">
      <span>
        {range ? 'confidence' : 'rule confidence'} {formatConfidence(confidence)}
      </span>
      {range && <span>{formatConfidenceRange(interval[0], interval[1])}</span>}
    </span>
  )
}

/** The docket stamp: what the case came to. */
export function OutcomeStamp({ outcome, status, vasp, confidence, interval, whatWouldChange, size = 'sm', tilt, className }: OutcomeStampProps) {
  const look = lookOf(outcome, status)
  const { word, box } = LOOK[look]

  if (size === 'sm')
    return (
      <span
        data-testid="outcome-stamp"
        data-outcome={outcome ?? status ?? 'pending'}
        className={cx(
          'inline-flex h-6 max-w-full items-center gap-1.5 whitespace-nowrap rounded-sm border-2 border-current px-1.5 text-xs font-semibold',
          look === 'insufficient' || look === 'pending' ? 'border-dashed' : '',
          box,
          className,
        )}
      >
        <span className="uppercase tracking-wide">{word}</span>
        {look === 'attributed' && vasp && <span className="display truncate text-sm">{vasp}</span>}
      </span>
    )

  return (
    <div className={cx('inline-flex max-w-full flex-col items-start gap-2', className)}>
      <div
        data-testid="outcome-stamp"
        data-outcome={outcome ?? status ?? 'pending'}
        className={cx('stamp inline-flex min-w-[168px] max-w-full flex-col gap-0.5 px-3.5 py-2.5', box, tilt && 'stamp-tilt')}
      >
        <span className="text-xs font-semibold uppercase tracking-[0.08em]">{word}</span>
        {look === 'attributed' && <span className="display text-xl leading-8">{vasp ?? 'Unnamed exchange'}</span>}
        {look === 'insufficient' && <span className="display text-lg">No exchange named</span>}
        {look === 'sanctioned' && vasp && <span className="text-sm font-medium">Nearest exchange: {vasp}</span>}
        {(look === 'attributed' || (look === 'sanctioned' && vasp)) && confidence != null && (
          <ConfidenceLines confidence={confidence} interval={interval} />
        )}
      </div>
      {look === 'insufficient' && whatWouldChange && (
        <p className="max-w-[320px] text-xs text-muted">
          <span className="font-semibold text-fg">What would change this:</span> {whatWouldChange}
        </p>
      )}
    </div>
  )
}
