import type { Chain, RiskInfo } from '../api/models'
import { cx } from '../lib/cx'
import { RISK_BASIS, RISK_ORDER, RISK_WORDS, RiskTag } from './RiskTag'
import { TxHash } from './TxHash'

const FLOOR = { low: 0, medium: 25, high: 50, severe: 75 } as const
const SHOWN = 3

/** The score on its scale: one bar from 0 to 100 with the three class boundaries ruled on it. */
function Scale({ score, severe }: { score: number; severe: boolean }) {
  return (
    <div
      role="meter"
      aria-label="Risk score"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={score}
      aria-valuetext={`${score} of 100. ${RISK_BASIS}`}
      className="flex flex-col gap-1"
    >
      <div className="relative h-2.5 bg-surface-3">
        <div className={cx('anim-bar h-full', severe ? 'bg-danger' : 'bg-ink')} style={{ width: `${score}%` }} />
        {RISK_ORDER.slice(1).map((c) => (
          <span key={c} aria-hidden className="absolute top-[-3px] h-[16px] w-px bg-ink-dim" style={{ left: `${FLOOR[c]}%` }} />
        ))}
      </div>
      <div aria-hidden className="relative h-4 text-2xs text-ink-soft">
        {RISK_ORDER.map((c) => (
          <span key={c} className="absolute whitespace-nowrap" style={{ left: `${FLOOR[c]}%`, paddingLeft: c === 'low' ? 0 : 3 }}>
            {RISK_WORDS[c]} {FLOOR[c]}+
          </span>
        ))}
      </div>
    </div>
  )
}

/** A wallet's or a case's risk: the class, the score on its scale, what the score is, and each
 *  indicator with its points, the sentence it rests on and the transactions behind it. */
export function RiskPanel({ risk, chain, subject }: { risk: RiskInfo; chain: Chain; subject: string }) {
  if (!risk.risk_class || risk.score == null)
    return (
      <div className="flex flex-col gap-2">
        <RiskTag risk={null} />
        <p className="max-w-prose text-base text-ink-soft">
          {subject} has no label and is in no finished case, so there is nothing to score. Trace it to assess it.
        </p>
      </div>
    )
  return (
    <div className="flex flex-col gap-4">
      <div className="grid items-start gap-x-8 gap-y-3 md:grid-cols-[auto_minmax(0,1fr)]">
        <div className="flex items-center gap-3">
          <span className={cx('figure', risk.risk_class === 'severe' ? 'text-danger' : 'text-ink')} style={{ fontSize: 34 }}>
            {risk.score}
          </span>
          <span className="flex flex-col gap-1">
            <span className="text-2xs text-ink-soft">of 100</span>
            <RiskTag risk={risk.risk_class} />
          </span>
        </div>
        <Scale score={risk.score} severe={risk.risk_class === 'severe'} />
      </div>

      <p className="max-w-[82ch] border-l-2 border-ink-dim pl-3 text-base text-ink">
        {risk.basis}
        {risk.source && <span className="mt-0.5 block text-sm text-ink-soft">The indicator list follows {risk.source}. The points are this tool's.</span>}
      </p>

      {risk.indicators.length === 0 ? (
        <p className="text-base text-ink">No indicator is present.</p>
      ) : (
        <ol aria-label="Indicators present" className="flex flex-col">
          {risk.indicators.map((i) => (
            <li key={i.code + (i.case_id ?? '')} className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-3 border-t border-rule-soft py-2.5 first:border-t-0 first:pt-0">
              <span className="tabular pt-0.5 text-right font-mono text-base font-medium text-ink" title={`${i.points} points`}>
                +{i.points}
              </span>
              <div className="flex min-w-0 flex-col gap-1">
                <p className="text-base font-semibold text-ink">{i.name}</p>
                <p className="text-base text-ink">{i.text}</p>
                {i.fatf_category && <p className="text-sm text-ink-soft">Filed under: {i.fatf_category}</p>}
                {i.tx_hashes.length > 0 && (
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-soft">
                    <span>{i.tx_hashes.length === 1 ? 'Transaction' : `${i.tx_hashes.length} transactions`}</span>
                    {i.tx_hashes.slice(0, SHOWN).map((h) => (
                      <TxHash key={h} hash={h} chain={chain} />
                    ))}
                    {i.tx_hashes.length > SHOWN && <span>and {i.tx_hashes.length - SHOWN} more, in the case file</span>}
                  </p>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
