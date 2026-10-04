import type { RiskClass } from '../api/models'
import { cx } from '../lib/cx'

export const RISK_ORDER: RiskClass[] = ['low', 'medium', 'high', 'severe']
export const RISK_WORDS: Record<RiskClass, string> = { low: 'Low', medium: 'Medium', high: 'High', severe: 'Severe' }

/** What the score is, wherever it is shown (the API sends the same sentence as `risk.basis`). */
export const RISK_BASIS = 'An indicator score from published red-flag rules. Not a probability, and not measured against known outcomes.'

const BOX: Record<RiskClass, string> = {
  low: 'border-rule text-ink-soft',
  medium: 'border-ink-dim text-ink',
  high: 'border-ink bg-surface-2 font-semibold text-ink',
  severe: 'border-danger bg-danger-wash font-semibold text-danger',
}

/** The higher of two classes; null counts as "none". */
export function worst(a: RiskClass | null | undefined, b: RiskClass | null | undefined): RiskClass | null {
  const rank = (c: RiskClass | null | undefined) => (c ? RISK_ORDER.indexOf(c) : -1)
  return (rank(a) >= rank(b) ? a : b) ?? null
}

/** Four rising steps, as many filled as the class is high: the class is told by shape and by the
 *  word beside it, never by colour alone. */
export function RiskSteps({ risk, size = 13 }: { risk: RiskClass; size?: number }) {
  const filled = RISK_ORDER.indexOf(risk) + 1
  return (
    <svg aria-hidden width={size} height={size} viewBox="0 0 13 13" className="shrink-0">
      {[0, 1, 2, 3].map((i) => {
        const h = 4 + i * 3
        return <rect key={i} x={i * 3.4 + 0.5} y={12.5 - h} width={2} height={h} fill={i < filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={0.8} />
      })}
    </svg>
  )
}

/** A risk class: steps, the word, and (when given) the score out of 100. `kind` says whose class
 *  it is when a wallet's and a flow's sit side by side. A null class reads "Not assessed". */
export function RiskTag({ risk, score, kind = 'risk', className }: { risk: RiskClass | null | undefined; score?: number | null; kind?: string; className?: string }) {
  if (!risk)
    return (
      <span data-testid="risk-tag" data-risk="none" className={cx('inline-flex h-6 shrink-0 items-center whitespace-nowrap rounded-sm border border-dashed border-rule px-1.5 text-sm text-ink-soft', className)}>
        Not assessed
      </span>
    )
  return (
    <span
      data-testid="risk-tag"
      data-risk={risk}
      title={RISK_BASIS}
      className={cx('inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-sm', BOX[risk], className)}
    >
      <RiskSteps risk={risk} />
      {RISK_WORDS[risk]} {kind}
      {score != null && <span className="tabular font-mono font-normal">{score}/100</span>}
    </span>
  )
}
