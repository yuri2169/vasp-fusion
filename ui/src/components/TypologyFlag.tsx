import { Info, Lightbulb, ShieldAlert, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { TypologyCode, TypologyFlag as Flag } from '../api/models'
import { cx } from '../lib/cx'

/** The investigator's name for each pattern (docs/api_contract.md, "Flags"). */
export const TYPOLOGY_NAMES: Record<TypologyCode, string> = {
  sanctioned_contact: 'Sanctioned contact',
  mixer_contact: 'Mixer contact',
  bridge_hop: 'Bridge',
  peel_chain: 'Peel chain',
  rapid_forwarding: 'Rapid forwarding',
  coinjoin_shape: 'CoinJoin shape',
  fan_out: 'Fan-out',
  fan_in: 'Fan-in',
  round_amounts: 'Round amounts',
  deposit_like: 'Behaves like a deposit address',
}

type Kind = 'alert' | 'pattern' | 'note' | 'lead'

/** Severity in a word, an icon and a colour: never colour alone. */
const KINDS: Record<Kind, { word: string; Icon: LucideIcon; box: string; accent: string }> = {
  alert: { word: 'Alert', Icon: ShieldAlert, box: 'border-seal-text bg-seal-wash', accent: 'text-seal-text' },
  pattern: { word: 'Pattern', Icon: TriangleAlert, box: 'border-rule-strong bg-surface', accent: 'text-fg' },
  note: { word: 'Note', Icon: Info, box: 'border-rule bg-surface', accent: 'text-muted' },
  // A lead from the deposit-address model: something to look into, never part of the answer.
  lead: { word: 'Lead', Icon: Lightbulb, box: 'border-dashed border-verified-text bg-surface', accent: 'text-verified-text' },
}

const kindOf = (flag: Flag): Kind =>
  flag.code === 'deposit_like' ? 'lead' : flag.severity === 'high' ? 'alert' : flag.severity === 'warn' ? 'pattern' : 'note'

/** A pattern seen in the traced money. `compact` is the name alone, for a table cell or a summary row. */
export function TypologyFlag({ flag, compact = false }: { flag: Flag; compact?: boolean }) {
  const { word, Icon, box, accent } = KINDS[kindOf(flag)]
  const head = (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <Icon size={14} aria-hidden className={cx('shrink-0', accent)} />
      <span className={cx('text-xs font-medium uppercase tracking-wide', accent)}>{word}</span>
      <span className="text-sm font-semibold text-fg">{TYPOLOGY_NAMES[flag.code]}</span>
    </span>
  )
  if (compact) return <span className={cx('inline-flex h-7 items-center rounded border px-2', box)}>{head}</span>
  return (
    <div className={cx('flex flex-col gap-1.5 rounded border px-3 py-2.5', box)}>
      {head}
      <p className="text-sm text-fg">{flag.text}</p>
    </div>
  )
}
