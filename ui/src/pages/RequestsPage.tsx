import { FileText, Search } from 'lucide-react'
import { useMemo } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import type { RequestDetail, RequestStatus } from '../api/models'
import { useCases, useDesk, useRequests } from '../api/queries'
import { buttonClass } from '../components/Button'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { DeskNav } from '../desk/DeskNav'
import { RoutingSlip } from '../desk/RoutingSlip'
import { StatusTag } from '../desk/StatusTag'
import { ASK_WORDS, isOpen, isOverdue, STATUS_ORDER, STATUS_WORDS } from '../desk/status'
import { cx } from '../lib/cx'
import { formatDate } from '../lib/format'

type StatusFilter = 'all' | 'open' | 'awaiting' | RequestStatus

/** A reply is still owed: the dashboard's "awaiting a reply" count opens this filter. */
const isAwaiting = (r: RequestDetail) => r.status === 'sent' || r.status === 'acknowledged'

const matchesStatus = (r: RequestDetail, filter: StatusFilter) => filter === 'all' || (filter === 'open' ? isOpen(r.status) : filter === 'awaiting' ? isAwaiting(r) : r.status === filter)

/** Everything a search can find a request by: its reference, the exchange, its cases, its wallets, the officer. */
function haystack(r: RequestDetail): string {
  const l = r.letter
  return [r.reference, r.id, r.vasp, l.to, l.officer, ...r.case_ids, ...(l.cases ?? []).flatMap((c) => [c.case_ref, c.complaint_no, c.wallet]), ...l.wallets.map((w) => w.address)]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

/** The requests register: every request ever drafted, with its routing slip. Filters live in the
 *  address (?status=&vasp=&q=), so a filtered view can be linked to and the back button undoes it. */
export function RequestsPage() {
  const requests = useRequests()
  const desk = useDesk()
  const cases = useCases()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  const all = useMemo(() => requests.data?.items ?? [], [requests.data])
  const status = (params.get('status') ?? 'all') as StatusFilter
  const vasp = params.get('vasp') ?? ''
  const q = params.get('q') ?? ''

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value && value !== 'all') next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const inScope = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return all.filter((r) => (!vasp || r.vasp === vasp) && (!needle || haystack(r).includes(needle)))
  }, [all, vasp, q])
  const shown = inScope.filter((r) => matchesStatus(r, status))

  const vasps = [...new Set(all.map((r) => r.vasp))].sort()
  const filters: StatusFilter[] = ['all', 'open', ...(status === 'awaiting' || all.some(isAwaiting) ? (['awaiting'] as const) : []), ...STATUS_ORDER.filter((s) => all.some((r) => r.status === s) || s === status)]
  const refOf = (id: string) => cases.data?.items.find((c) => c.id === id)?.case_ref ?? id

  const columns: Column<RequestDetail>[] = [
    {
      key: 'ref',
      header: 'Reference',
      // references are numbered in the order they were drafted
      sortValue: (r) => r.created_at + r.reference,
      cell: (r) => (
        <span className="flex flex-col">
          <span className="whitespace-nowrap font-mono text-base font-medium">{r.reference}</span>
          <span className="tabular whitespace-nowrap text-sm text-muted">drafted {formatDate(r.created_at)}</span>
        </span>
      ),
    },
    {
      key: 'vasp',
      header: 'Exchange',
      sortValue: (r) => r.vasp.toLowerCase(),
      cell: (r) => (
        <Link to={`/vasps/${encodeURIComponent(r.vasp)}`} className="title text-md text-fg underline-offset-2 hover:underline">
          {r.vasp}
        </Link>
      ),
    },
    {
      key: 'about',
      header: 'Cases and asks',
      cell: (r) => (
        <span className="flex flex-col">
          <span className="text-base">{r.case_ids.map(refOf).join(', ')}</span>
          <span className="text-sm text-muted">
            {r.letter.wallets.length} {r.letter.wallets.length === 1 ? 'wallet' : 'wallets'} · {r.letter.asks.map((a) => ASK_WORDS[a].toLowerCase().replace('kyc', 'KYC')).join(', ')}
          </span>
        </span>
      ),
    },
    { key: 'status', header: 'Status', sortValue: (r) => STATUS_ORDER.indexOf(r.status), cell: (r) => <StatusTag status={r.status} /> },
    { key: 'slip', header: 'Routing slip', cell: (r) => <RoutingSlip history={r.status_history} status={r.status} /> },
    {
      key: 'due',
      header: 'Reply due',
      align: 'right',
      sortValue: (r) => r.due ?? null,
      cell: (r) =>
        r.due ? (
          <span className={cx('tabular whitespace-nowrap text-base', isOverdue(r) ? 'font-medium text-seal-text' : 'text-muted')}>
            {formatDate(r.due)}
            {isOverdue(r) && <span className="block text-sm">overdue</span>}
          </span>
        ) : (
          <span className="whitespace-nowrap text-base text-muted">not sent</span>
        ),
    },
  ]

  return (
    <>
      <PageHeader title="Request desk">Every request ever drafted, with where it stands. Open one to read its letter.</PageHeader>
      <DeskNav counts={{ exchanges: desk.data?.rows.length, requests: requests.data?.items.length }} />
      {requests.isError ? (
        <ErrorState
          title="The requests could not be loaded"
          detail={requests.error instanceof ApiError ? requests.error.detail : 'Try again.'}
          onRetry={() => void requests.refetch()}
        />
      ) : requests.data && all.length === 0 ? (
        <EmptyState
          title="No request has been drafted"
          icon={<FileText size={22} aria-hidden />}
          action={
            <Link to="/desk" className={buttonClass('primary')}>
              Go to the desk
            </Link>
          }
        >
          A request is drafted from the desk, one per exchange, once a case names that exchange.
        </EmptyState>
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-1">
              {filters.map((f) => {
                const n = inScope.filter((r) => matchesStatus(r, f)).length
                const on = status === f
                return (
                  <button
                    key={f}
                    type="button"
                    aria-pressed={on}
                    onClick={() => set('status', f)}
                    className={cx(
                      'inline-flex h-7 items-center gap-1.5 rounded border px-2.5 text-sm',
                      on ? 'border-fg bg-fg font-semibold text-page' : 'border-rule-strong bg-surface text-fg hover:bg-sunk',
                    )}
                  >
                    {f === 'all' ? 'All' : f === 'open' ? 'Open' : f === 'awaiting' ? 'Awaiting a reply' : STATUS_WORDS[f]}
                    <span className={cx('tabular font-mono', !on && 'text-muted')}>{n}</span>
                  </button>
                )
              })}
            </div>
            <label className="flex items-center gap-2 text-sm text-muted">
              Exchange
              <select
                value={vasp}
                onChange={(e) => set('vasp', e.target.value)}
                className="h-7 rounded border border-rule-strong bg-surface px-1.5 text-sm text-fg"
              >
                <option value="">All exchanges</option>
                {vasps.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </label>
            <label className="relative ml-auto flex items-center">
              <span className="sr-only">Search the requests</span>
              <Search size={13} aria-hidden className="pointer-events-none absolute left-2 text-muted" />
              <input
                type="search"
                value={q}
                onChange={(e) => set('q', e.target.value)}
                placeholder="Reference, case, wallet"
                className="h-7 w-56 rounded border border-rule-strong bg-surface pl-7 pr-2 text-sm text-fg placeholder:text-muted"
              />
            </label>
          </div>
          <DataTable
            caption="Requests"
            columns={columns}
            rows={shown}
            rowKey={(r) => r.id}
            loading={requests.isPending}
            initialSort={{ key: 'ref', dir: 'desc' }}
            onRowOpen={(r) => navigate(`/requests/${encodeURIComponent(r.id)}`)}
            empty="No request matches these filters."
          />
        </>
      )}
    </>
  )
}
