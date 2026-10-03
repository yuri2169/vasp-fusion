import { Ban, CircleCheck, CircleDashed, FilePen, Hourglass, Lock, Send, Stamp, Undo2, type LucideIcon } from 'lucide-react'
import { cx } from '../lib/cx'
import { STATUS_WORDS, type DeskStatus } from './status'

const LOOK: Record<DeskStatus, { Icon: LucideIcon; box: string }> = {
  not_requested: { Icon: CircleDashed, box: 'border-dashed border-rule-strong text-muted' },
  drafted: { Icon: FilePen, box: 'border-dashed border-rule-strong text-fg' },
  approved: { Icon: Stamp, box: 'border-rule-strong text-fg' },
  sent: { Icon: Send, box: 'border-rule-strong bg-sunk text-fg' },
  acknowledged: { Icon: Hourglass, box: 'border-rule-strong bg-sunk text-fg' },
  answered: { Icon: CircleCheck, box: 'border-verified-text text-verified-text' },
  freeze_confirmed: { Icon: Lock, box: 'border-verified-text bg-verified-wash text-verified-text' },
  refused: { Icon: Ban, box: 'border-seal-text text-seal-text' },
  withdrawn: { Icon: Undo2, box: 'border-dashed border-rule-strong text-muted line-through' },
}

/** Where a request stands, as an icon and a word (never colour alone). */
export function StatusTag({ status, className }: { status: DeskStatus; className?: string }) {
  const { Icon, box } = LOOK[status]
  return (
    <span
      data-testid="status-tag"
      data-status={status}
      className={cx('inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-xs font-medium', box, className)}
    >
      <Icon size={13} aria-hidden className="shrink-0" />
      {STATUS_WORDS[status]}
    </span>
  )
}
