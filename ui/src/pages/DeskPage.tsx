import { CalendarClock, Inbox } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import type { DeskRow, FollowUp } from '../api/models'
import { useCases, useDesk, useRequests } from '../api/queries'
import { Button, buttonClass } from '../components/Button'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { DeskNav } from '../desk/DeskNav'
import { DraftDialog } from '../desk/DraftDialog'
import { StatusTag } from '../desk/StatusTag'
import { FOLLOW_UP_WORDS, STATUS_ORDER } from '../desk/status'
import { formatDate, formatUsd } from '../lib/format'

const vaspLink = (name: string) => `/vasps/${encodeURIComponent(name)}`
const requestLink = (id: string) => `/requests/${encodeURIComponent(id)}`

/** A wallet no request asks about yet: the row offers a draft. */
const canDraft = (row: DeskRow) => row.status === 'not_requested' || (row.unrequested_wallets ?? 0) > 0

/** What is past its day, first on the page: an overdue reply is the one thing here that gets worse by waiting. */
function FollowUps({ items }: { items: FollowUp[] }) {
  return (
    <section aria-labelledby="follow-up" className="mb-7">
      <h2 id="follow-up" className="eyebrow mb-2">
        Follow up
      </h2>
      {items.length === 0 ? (
        <p className="rounded-md border border-dashed border-rule-strong px-4 py-3 text-sm text-muted">Nothing is overdue. No reply is past its day.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map((f) => (
            <li
              key={f.request_id + f.kind}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border border-seal-text bg-seal-wash px-4 py-3"
            >
              <CalendarClock size={18} aria-hidden className="shrink-0 text-seal-text" />
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold uppercase tracking-wide text-seal-text">{FOLLOW_UP_WORDS[f.kind]}</p>
                <p className="text-sm text-fg">{f.text}</p>
              </div>
              <span className="tabular whitespace-nowrap font-mono text-xs text-muted">due {formatDate(f.due)}</span>
              <Link to={requestLink(f.request_id)} aria-label={`Open request to ${f.vasp}`} className={buttonClass('secondary', 'sm')}>
                Open request
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** The request desk: the unit of work is an exchange, not a complaint. One row per exchange,
 *  its wallets gathered across cases, where its request stands and what to do next. */
export function DeskPage() {
  const desk = useDesk()
  const cases = useCases()
  const requests = useRequests()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  // The case page's "Draft request to ‹exchange›" lands here with ?vasp=&case=.
  const drafting = params.get('vasp')
  const fromCase = params.get('case')
  const openDraft = (vasp: string) => setParams({ vasp })
  const closeDraft = () => setParams({}, { replace: true })

  const refOf = (id: string) => cases.data?.items.find((c) => c.id === id)?.case_ref ?? id

  const columns: Column<DeskRow>[] = [
    {
      key: 'vasp',
      header: 'Exchange',
      sortValue: (r) => r.vasp.toLowerCase(),
      cell: (r) => (
        <Link to={vaspLink(r.vasp)} className="display text-base text-fg underline-offset-2 hover:underline">
          {r.vasp}
        </Link>
      ),
    },
    {
      key: 'wallets',
      header: 'Wallets',
      align: 'right',
      sortValue: (r) => r.wallet_count,
      cell: (r) => <span className="tabular font-mono text-sm">{r.wallet_count}</span>,
    },
    {
      key: 'usd',
      header: 'Traced, USD',
      align: 'right',
      sortValue: (r) => r.total_usd,
      cell: (r) => (
        <span className="tabular whitespace-nowrap font-mono text-sm font-medium" title="US-dollar stablecoins only; other assets are not converted">
          {formatUsd(r.total_usd)}
        </span>
      ),
    },
    {
      key: 'cases',
      header: 'Cases',
      cell: (r) => (
        <span className="flex flex-wrap gap-x-2 gap-y-0.5">
          {r.case_ids.map((id) => (
            <Link key={id} to={`/cases/${encodeURIComponent(id)}`} className="whitespace-nowrap text-sm text-fg underline decoration-rule-strong underline-offset-2 hover:decoration-current">
              {refOf(id)}
            </Link>
          ))}
        </span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      sortValue: (r) => (r.status === 'not_requested' ? -1 : STATUS_ORDER.indexOf(r.status)),
      cell: (r) => <StatusTag status={r.status} />,
    },
    {
      key: 'next',
      header: 'Next action',
      cell: (r) => (
        <span className="flex items-center justify-between gap-3">
          <span className="min-w-0 text-sm text-fg">{r.next_action}</span>
          <span className="flex shrink-0 gap-1.5">
            {r.last_request_id && (
              <Link to={requestLink(r.last_request_id)} aria-label={`Open request to ${r.vasp}`} className={buttonClass('secondary', 'sm')}>
                Open request
              </Link>
            )}
            {canDraft(r) && (
              <Button size="sm" aria-label={`Draft request to ${r.vasp}`} onClick={() => openDraft(r.vasp)}>
                Draft request
              </Button>
            )}
          </span>
        </span>
      ),
    },
  ]

  const rows = desk.data?.rows ?? []

  return (
    <>
      <PageHeader title="Request desk">
        One row per exchange: its wallets across every case, where its request stands, and what to do next.
      </PageHeader>
      <DeskNav counts={{ exchanges: desk.data?.rows.length, requests: requests.data?.items.length }} />
      {desk.isError ? (
        <ErrorState
          title="The desk could not be loaded"
          detail={desk.error instanceof ApiError ? desk.error.detail : 'Try again.'}
          onRetry={() => void desk.refetch()}
        />
      ) : desk.data && rows.length === 0 ? (
        <EmptyState
          title="No exchange to write to yet"
          icon={<Inbox size={22} aria-hidden />}
          action={
            <Link to="/cases/new" className={buttonClass('primary')}>
              Open a case
            </Link>
          }
        >
          An exchange appears here once a finished case names it at or above the 0.60 naming bar. Trace a wallet to start.
        </EmptyState>
      ) : (
        <>
          {desk.data && <FollowUps items={desk.data.follow_ups} />}
          <h2 className="eyebrow mb-2">Exchanges</h2>
          <DataTable
            caption="Exchanges with traced wallets"
            columns={columns}
            rows={rows}
            rowKey={(r) => r.vasp}
            loading={desk.isPending}
            onRowOpen={(r) => navigate(vaspLink(r.vasp))}
          />
          <p className="mt-2 text-xs text-muted">
            Traced, USD counts US-dollar stablecoins only. The day a reply is due is an office reminder set on the server, not a period set by law.
          </p>
        </>
      )}
      {drafting && <DraftDialog key={drafting} vasp={drafting} preselect={fromCase ? [fromCase] : undefined} onClose={closeDraft} />}
    </>
  )
}
