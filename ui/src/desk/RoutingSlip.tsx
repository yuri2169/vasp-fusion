import { Check, Minus, X } from 'lucide-react'
import type { RequestStatus, StatusEvent } from '../api/models'
import { Tip, useTip } from '../components/Tip'
import { cx } from '../lib/cx'
import { formatDate, formatDateTime } from '../lib/format'
import { slipSteps, type SlipStep } from './status'

/** A table row has room for a short word; the whole of it is in the box's hover card and its name. */
const SHORT: Record<string, string> = { Acknowledged: 'Ack.', 'Freeze confirmed': 'Frozen' }

const STATE_WORDS: Record<SlipStep['state'], string> = {
  done: '',
  next: 'awaited',
  todo: 'not yet',
  skipped: 'passed over',
  void: '',
}

/** "3 Oct": the register's rows have room for the day only; the whole time is one hover away. */
const dayOnly = (iso: string) => formatDate(iso).replace(/ \d{4}$/, '')

function sentence(step: SlipStep): string {
  if (!step.event) return `${step.label}: ${STATE_WORDS[step.state]}`
  const who = step.event.by ? ` by ${step.event.by}` : ''
  return `${step.label} on ${formatDateTime(step.event.at)}${who}${step.event.note ? `. ${step.event.note}` : ''}`
}

function Mark({ state }: { state: SlipStep['state'] }) {
  if (state === 'done') return <Check size={12} strokeWidth={3} aria-hidden className="shrink-0 text-verified-text" />
  if (state === 'void') return <X size={12} strokeWidth={3} aria-hidden className="shrink-0 text-seal-text" />
  if (state === 'skipped') return <Minus size={12} aria-hidden className="shrink-0 text-muted" />
  return null
}

function Cell({ step }: { step: SlipStep }) {
  const tip = useTip()
  const stamped = step.state === 'done' || step.state === 'void'
  return (
    <li
      {...tip.bind}
      data-state={step.state}
      aria-label={sentence(step)}
      className={cx(
        'flex h-10 min-w-0 flex-1 flex-col justify-center border-y border-l px-1.5 first:rounded-l-sm last:rounded-r-sm last:border-r',
        stamped ? 'border-rule-strong bg-surface' : 'border-dashed border-rule-strong',
        step.state === 'void' && 'bg-seal-wash',
        step.state === 'next' && 'bg-sunk',
      )}
    >
      <span className={cx('flex items-center gap-1 truncate text-xs', stamped ? 'font-medium text-fg' : 'text-muted')}>
        {step.state !== 'done' && <Mark state={step.state} />}
        {SHORT[step.label] ?? step.label}
      </span>
      <span className="tabular truncate font-mono text-xs text-muted">{step.event ? dayOnly(step.event.at) : step.state === 'next' ? 'awaited' : ' '}</span>
      <Tip id={tip.id} anchor={tip.anchor}>
        {sentence(step)}
      </Tip>
    </li>
  )
}

/** The request's routing slip: the boxes a file's slip has, in order, each stamped with its day
 *  once it happened. A box not reached is dashed and empty. `row` fits a table row; `column`
 *  is the slip in full beside the letter, with who and the note of each step as they were recorded. */
export function RoutingSlip({
  history,
  status,
  layout = 'row',
}: {
  history: StatusEvent[]
  status: RequestStatus
  layout?: 'row' | 'column'
}) {
  const steps = slipSteps(history, status)

  if (layout === 'row')
    return (
      <ol aria-label="Routing slip" data-testid="routing-slip" className="flex w-[350px] max-w-full">
        {steps.map((step) => (
          <Cell key={step.key} step={step} />
        ))}
      </ol>
    )

  return (
    <ol aria-label="Routing slip" data-testid="routing-slip" className="rounded border border-rule-strong bg-surface">
      {steps.map((step) => {
        const stamped = step.state === 'done' || step.state === 'void'
        return (
          <li
            key={step.key}
            data-state={step.state}
            className={cx(
              'border-b border-rule px-3 py-2 last:border-b-0',
              !stamped && 'border-dashed',
              step.state === 'void' && 'bg-seal-wash',
              step.state === 'next' && 'bg-sunk',
            )}
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className={cx('flex items-center gap-1.5 text-sm', stamped ? 'font-semibold text-fg' : 'text-muted')}>
                <span className="inline-flex w-3 justify-center">
                  <Mark state={step.state} />
                </span>
                {step.label}
              </span>
              <span className="tabular whitespace-nowrap font-mono text-xs text-muted">
                {step.event ? formatDateTime(step.event.at) : STATE_WORDS[step.state]}
              </span>
            </div>
            {step.event && (step.event.note || step.event.by) && (
              <p className="mt-0.5 pl-[18px] text-xs text-muted [overflow-wrap:anywhere]">
                {step.event.by && <span className="font-medium">{step.event.by}. </span>}
                {step.event.note}
              </p>
            )}
          </li>
        )
      })}
    </ol>
  )
}
