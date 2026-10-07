import { Link } from 'react-router'
import type { WriteOrder, WriteOrderRow } from '../api/models'
import { buttonClass } from '../components/Button'
import { StatusTag } from '../desk/StatusTag'
import { letterOfRequestLink } from '../desk/status'
import { formatPercent } from '../lib/format'

const ROUTE_WORDS: Record<WriteOrderRow['route'], string> = {
  domestic_notice: 'Notice under Indian law',
  direct_channel: "The exchange's own channel",
  letter_of_request: 'Letter of request',
}

/** Who to write to first when the money reached more than one exchange: the order, and for each
 *  exchange the reasons the server gave, word for word. With one exchange it says where to write.
 *  It never says how fast an exchange answers: the tool holds no cited figure for that. */
export function WriteOrderPanel({ order, caseId, compact = false }: { order: WriteOrder; caseId: string; compact?: boolean }) {
  const many = order.exchanges.length > 1
  const title = many ? 'Who to write to first' : 'Where to write'
  return (
    <section aria-label={compact ? undefined : title} className={compact ? undefined : 'panel mt-4 p-4'}>
      {!compact && <h2 className="eyebrow mb-1">{title}</h2>}
      <p className="mb-3 max-w-[100ch] text-sm text-muted">
        {many && `${order.rule} `}
        {order.note}
      </p>
      <ol className="flex flex-col divide-y divide-rule-soft">
        {order.exchanges.map((x) => (
          <li key={x.vasp} className="grid gap-x-4 gap-y-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[2.5rem_minmax(0,1fr)_auto]">
            <span className="tabular font-mono text-xl font-semibold text-fg">
              {many && (
                <>
                  <span className="sr-only">Number </span>
                  {x.rank}
                </>
              )}
            </span>
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Link to={`/vasps/${encodeURIComponent(x.vasp)}`} className="title text-md text-fg underline-offset-2 hover:underline">
                  {x.vasp}
                </Link>
                <span className="tabular font-mono text-sm text-ink-soft">{formatPercent(x.share_of_funds)} of the funds</span>
                <span className="rounded-sm border border-rule-strong px-1.5 py-0.5 text-sm text-ink-soft">{ROUTE_WORDS[x.route]}</span>
                {x.request_status && <StatusTag status={x.request_status} />}
              </p>
              <ul className="mt-1.5 flex flex-col gap-0.5">
                {x.reasons.map((reason) => (
                  <li key={reason} className="max-w-[90ch] text-base text-fg [overflow-wrap:anywhere]">
                    {reason}
                  </li>
                ))}
              </ul>
            </div>
            <div className="flex flex-wrap items-start gap-1.5 sm:flex-col sm:items-stretch">
              {x.request_id ? (
                <Link to={`/requests/${encodeURIComponent(x.request_id)}`} aria-label={`Open request to ${x.vasp}`} className={buttonClass('secondary', 'sm')}>
                  Open request
                </Link>
              ) : (
                <Link
                  to={`/desk?vasp=${encodeURIComponent(x.vasp)}&case=${encodeURIComponent(caseId)}`}
                  aria-label={`Draft request to ${x.vasp}`}
                  className={buttonClass(x.route === 'letter_of_request' ? 'secondary' : 'primary', 'sm')}
                >
                  Draft request
                </Link>
              )}
              {x.letter_of_request && (
                <Link to={letterOfRequestLink(x.vasp, caseId)} aria-label={`Letter-of-request draft for ${x.vasp}`} className={buttonClass('secondary', 'sm')}>
                  Letter-of-request draft
                </Link>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}
