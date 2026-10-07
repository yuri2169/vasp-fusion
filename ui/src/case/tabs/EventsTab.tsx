import { Circle, CircleCheck, CircleDashed } from 'lucide-react'
import { Link } from 'react-router'
import type { CaseTimeline, TimelineStep } from '../../api/models'
import { EmptyState } from '../../components/EmptyState'
import { cx } from '../../lib/cx'
import { elapsedWords } from '../../desk/status'
import { formatDate } from '../../lib/format'

const pad = (n: number) => String(n).padStart(2, '0')
/** To the second: the steps of one trace are seconds apart. */
const clock = (iso: string) => {
  const d = new Date(iso)
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`
}

const STATE_WORDS: Record<TimelineStep['state'], string> = {
  done: 'Recorded',
  pending: 'Pending',
  not_recorded: 'Time not on record',
}
const ICONS = { done: CircleCheck, pending: CircleDashed, not_recorded: Circle }

function Step({ step, first, last }: { step: TimelineStep; first: TimelineStep | undefined; last: boolean }) {
  const Icon = ICONS[step.state]
  const done = step.state === 'done'
  return (
    <li data-state={step.state} className="grid grid-cols-[20px_minmax(0,1fr)] gap-x-3">
      <span className="flex flex-col items-center" aria-hidden>
        <Icon size={16} className={cx('mt-1 shrink-0', done ? 'text-verified-text' : 'text-muted')} />
        {!last && <span className={cx('mt-1 w-px flex-1', done ? 'bg-rule-strong' : 'border-l border-dashed border-rule-strong')} />}
      </span>
      <div className={cx('pb-5', !done && 'text-muted')}>
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span className={cx('text-base font-medium', done ? 'text-fg' : 'text-ink-soft')}>
            {step.request_id ? (
              <Link to={`/requests/${encodeURIComponent(step.request_id)}`} className="underline decoration-rule-strong underline-offset-2 hover:decoration-current">
                {step.label}
              </Link>
            ) : (
              step.label
            )}
          </span>
          {step.at ? (
            <time dateTime={step.at} className="tabular whitespace-nowrap font-mono text-sm text-ink-soft">
              {formatDate(step.at)}, {clock(step.at)}
            </time>
          ) : (
            <span className="text-sm uppercase tracking-wide text-muted">{STATE_WORDS[step.state]}</span>
          )}
        </p>
        {done && (
          <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-muted">
            {step.after_previous_s != null && <span>{elapsedWords(step.after_previous_s)} after the step before</span>}
            {step.since_first_s != null && step.since_first_s > 0 && first && step.after_previous_s !== step.since_first_s && (
              <span>
                {elapsedWords(step.since_first_s)} after "{first.label}"
              </span>
            )}
            {step.by && <span>by {step.by}</span>}
            {step.via === 'sahyog' && <span>through the SAHYOG gateway</span>}
            {step.source && <span>from the {step.source}</span>}
          </p>
        )}
        {step.detail && <p className="mt-0.5 max-w-[90ch] text-sm text-ink-soft [overflow-wrap:anywhere]">{step.detail}</p>}
      </div>
    </li>
  )
}

/** What happened on this case and when, read only from records the tool kept: the complaint,
 *  the trace, the requests and their replies. A step that has not happened is pending and has
 *  no time; nothing here is estimated. */
export function EventsTab({ timeline }: { timeline: CaseTimeline | null | undefined }) {
  if (!timeline || timeline.steps.length === 0)
    return (
      <EmptyState title="No case events to show">
        The events of a case are read from the tool's own records (complaints, the trace queue, the audit log, requests). None is available for this
        case here.
      </EmptyState>
    )
  const first = timeline.steps.find((s) => s.at)
  return (
    <section aria-label="Case events" className="panel p-4">
      <p className="mb-4 max-w-[90ch] text-sm text-muted">{timeline.note}</p>
      <ol className="flex flex-col">
        {timeline.steps.map((step, i) => (
          <Step key={`${step.key}-${step.request_id ?? ''}-${i}`} step={step} first={first} last={i === timeline.steps.length - 1} />
        ))}
      </ol>
    </section>
  )
}
