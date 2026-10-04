import { ArrowRightToLine, Cpu, Fuel, Route, Tag, type LucideIcon } from 'lucide-react'
import type { Chain, EvidenceItem } from '../api/models'
import { cx } from '../lib/cx'
import { TierTag } from './TierTag'
import { TxHash } from './TxHash'

type Kind = Exclude<EvidenceItem['kind'], 'counterfactual'>

/** What kind of proof an item is, in a word and an icon. */
const KINDS: Record<Kind, { word: string; Icon: LucideIcon }> = {
  label: { word: 'Label', Icon: Tag },
  path: { word: 'Path', Icon: Route },
  sweep: { word: 'Sweep', Icon: ArrowRightToLine },
  gas_payer: { word: 'Fee payer', Icon: Fuel },
  model: { word: 'Model', Icon: Cpu },
}

/** −0.80, +2.29: a typographic minus, so the sign reads at 12px. */
const signed = (w: number) => `${w < 0 ? '−' : '+'}${Math.abs(w).toFixed(2)}`

/** The reasons behind a named exchange, each in the backend's own sentence, each with the
 *  transactions that prove it. The deposit-address model's reasons are drawn as signed bars
 *  (how much each speaks for or against); its probability is a sentence, not a bar.
 *  The counterfactual item is the card's to show, next to the confidence it checks. */
export function EvidenceList({ items, chain, className }: { items: EvidenceItem[]; chain: Chain; className?: string }) {
  const shown = items.filter((item) => item.kind !== 'counterfactual')
  if (shown.length === 0) return null
  const strongest = Math.max(0, ...shown.filter((i) => i.kind === 'model' && i.weight != null).map((i) => Math.abs(i.weight!)))

  return (
    <ul className={cx('flex flex-col', className)}>
      {shown.map((item, i) => {
        const { word, Icon } = KINDS[item.kind as Kind]
        const reason = item.kind === 'model' && item.weight != null
        return (
          <li
            key={item.kind + i}
            className={cx('flex gap-2.5 border-t border-rule-soft py-2 first:border-t-0 first:pt-0 last:pb-0', reason && 'border-t-0 py-1.5 pl-6')}
          >
            {!reason && <Icon size={13} aria-hidden className="mt-0.5 shrink-0 text-ink-dim" />}
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              {!reason && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="eyebrow">{word}</span>
                  {item.tier && <TierTag tier={item.tier} size="sm" />}
                </div>
              )}
              <p className="break-words text-base text-fg">{item.text}</p>
              {reason && (
                <div className="flex items-center gap-2" title="SHAP value in log-odds: above 0 speaks for a deposit address, below 0 against">
                  <span className="h-1.5 w-24 shrink-0 bg-surface-3">
                    <span
                      data-testid="reason-bar"
                      data-sign={item.weight! < 0 ? 'against' : 'for'}
                      style={{ width: `${strongest > 0 ? Math.round((Math.abs(item.weight!) / strongest) * 100) : 0}%` }}
                      className={cx('anim-bar block h-full', item.weight! < 0 ? 'hatch' : 'bg-fusion')}
                    />
                  </span>
                  <span className="tabular font-mono text-sm text-muted">{signed(item.weight!)}</span>
                </div>
              )}
              {item.tx_hashes.length > 0 && (
                <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                  {item.tx_hashes.map((hash) => (
                    <TxHash key={hash} hash={hash} chain={chain} />
                  ))}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
