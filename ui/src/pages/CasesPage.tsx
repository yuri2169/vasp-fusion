import { FolderOpen, X } from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import type { CaseSummary, Desk } from '../api/models'
import { useCases, useDesk } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { buttonClass } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { PageHeader } from '../components/PageHeader'
import { CHAINS } from '../lib/chains'
import { formatConfidence, formatDate, formatInr } from '../lib/format'

const OUTCOME_ORDER = { ATTRIBUTED: 0, SANCTIONED_OR_MIXER_REACHED: 1, INSUFFICIENT_EVIDENCE: 2 }

const columns: Column<CaseSummary>[] = [
  {
    key: 'case',
    header: 'Case',
    sortValue: (c) => c.case_ref ?? c.id,
    cell: (c) => (
      <span className="flex items-center gap-2">
        <span className="font-medium text-fg">{c.case_ref ?? c.id}</span>
        {c.demo && (
          <span title="A real wallet from the demonstration set, traced from recorded chain responses. Verify (in the Audit tab) traces it again and compares." className="rounded-sm border border-dashed border-rule-strong px-1 text-xs text-muted">
            Recorded
          </span>
        )}
      </span>
    ),
  },
  {
    key: 'wallet',
    header: 'Wallet',
    cell: (c) => (
      <span className="flex items-center gap-2">
        <ChainBadge chain={c.chain} size="sm" />
        <AddressChip address={c.address} chain={c.chain} />
      </span>
    ),
  },
  {
    key: 'outcome',
    header: 'Outcome',
    sortValue: (c) => (c.outcome ? OUTCOME_ORDER[c.outcome] : 3),
    cell: (c) => <OutcomeStamp outcome={c.outcome ?? null} status={c.status} vasp={c.top_vasp} confidence={c.confidence} />,
  },
  {
    key: 'confidence',
    header: 'Confidence',
    align: 'right',
    sortValue: (c) => c.confidence ?? null,
    cell: (c) =>
      c.confidence != null ? (
        <span className="tabular font-mono text-sm">{formatConfidence(c.confidence)}</span>
      ) : (
        <span className="text-muted">none</span>
      ),
  },
  {
    key: 'lost',
    header: 'Reported loss',
    align: 'right',
    sortValue: (c) => c.amount_lost_inr ?? null,
    cell: (c) =>
      c.amount_lost_inr != null ? (
        <span className="tabular font-mono text-sm">{formatInr(c.amount_lost_inr)}</span>
      ) : (
        <span className="text-muted">not given</span>
      ),
  },
  {
    key: 'opened',
    header: 'Opened',
    align: 'right',
    sortValue: (c) => c.created_at,
    cell: (c) => <span className="tabular whitespace-nowrap text-sm text-muted">{formatDate(c.created_at)}</span>,
  },
]

const OUTCOME_WORDS: Record<string, string> = {
  ATTRIBUTED: 'An exchange is named',
  INSUFFICIENT_EVIDENCE: 'Insufficient evidence',
  SANCTIONED_OR_MIXER_REACHED: 'Sanctioned address or mixer reached',
}
const STATUS_FILTERS: Record<string, { words: string; has: (c: CaseSummary) => boolean }> = {
  tracing: { words: 'Being traced', has: (c) => c.status === 'queued' || c.status === 'running' },
  failed: { words: 'Trace failed', has: (c) => c.status === 'failed' },
  done: { words: 'Finished', has: (c) => c.status === 'done' },
}
const REPLIED = ['answered', 'freeze_confirmed', 'refused']

/** The dashboard's "open": being traced, or a wallet of the case is routed to an exchange that has not replied. */
function openIds(desk: Desk | undefined): Set<string> {
  const ids = new Set<string>()
  for (const row of desk?.rows ?? [])
    if ((row.unrequested_wallets ?? 0) > 0 || !REPLIED.includes(row.status)) for (const id of row.case_ids) ids.add(id)
  return ids
}

/** Every case, newest first. The dashboard's figures open this list filtered (?outcome=&status=&chain=&open=1). "Open a case" leads to the cover sheet (wallet, complaint, hop limit);
 *  the search bar stays the quick way in. */
export function CasesPage() {
  const cases = useCases()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const outcome = params.get('outcome')
  const status = params.get('status')
  const chain = params.get('chain')
  const open = params.get('open') === '1'
  const desk = useDesk(open)
  const waiting = openIds(desk.data)

  const filters = [
    outcome && OUTCOME_WORDS[outcome] && { key: 'outcome', words: OUTCOME_WORDS[outcome] },
    status && STATUS_FILTERS[status] && { key: 'status', words: STATUS_FILTERS[status].words },
    chain && chain in CHAINS && { key: 'chain', words: `On ${CHAINS[chain as keyof typeof CHAINS].name}` },
    open && { key: 'open', words: 'Open: being traced, or an exchange has not replied' },
  ].filter((f): f is { key: string; words: string } => Boolean(f))
  const all = cases.data?.items ?? []
  const shown = all.filter(
    (c) =>
      (!outcome || !OUTCOME_WORDS[outcome] || c.outcome === outcome) &&
      (!status || !STATUS_FILTERS[status] || STATUS_FILTERS[status].has(c)) &&
      (!chain || !(chain in CHAINS) || c.chain === chain) &&
      (!open || STATUS_FILTERS.tracing.has(c) || waiting.has(c.id)),
  )
  const drop = (key: string) => {
    const next = new URLSearchParams(params)
    next.delete(key)
    setParams(next, { replace: true })
  }
  const openCase = (
    <Link to="/cases/new" className={buttonClass('primary')}>
      Open a case
    </Link>
  )

  return (
    <>
      <PageHeader title="Cases" actions={cases.data && cases.data.items.length > 0 ? openCase : undefined}>
        One case per wallet: where its funds went, and which exchange to write to.
      </PageHeader>
      {cases.isError ? (
        <ErrorState
          title="The cases could not be loaded"
          detail={cases.error instanceof ApiError ? cases.error.detail : 'Try again.'}
          onRetry={() => void cases.refetch()}
        />
      ) : cases.data && cases.data.items.length === 0 ? (
        <EmptyState
          title="No cases yet"
          icon={<FolderOpen size={22} aria-hidden />}
          action={openCase}
        >
          Open the first case with a wallet address, or paste one in the search bar. Tron, Bitcoin and EVM wallets can be traced.
        </EmptyState>
      ) : (
        <>
          {filters.length > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Filters">
              <span className="text-muted">{cases.data ? `Showing ${shown.length} of ${all.length}:` : 'Showing:'}</span>
              {filters.map((f) => (
                <button
                  key={f.key}
                  type="button"
                  onClick={() => drop(f.key)}
                  aria-label={`Remove the filter: ${f.words}`}
                  className="inline-flex h-7 items-center gap-1.5 rounded border border-fg bg-fg px-2.5 text-xs font-semibold text-page"
                >
                  {f.words}
                  <X size={13} aria-hidden />
                </button>
              ))}
              <Link to="/cases" replace className="text-xs text-muted underline decoration-rule-strong underline-offset-2 hover:text-fg">
                Show all cases
              </Link>
            </div>
          )}
          <DataTable
            caption="Cases"
            columns={columns}
            rows={shown}
            rowKey={(c) => c.id}
            loading={cases.isPending}
            initialSort={{ key: 'opened', dir: 'desc' }}
            onRowOpen={(c) => navigate(`/cases/${encodeURIComponent(c.id)}`)}
            empty="No case matches these filters."
          />
        </>
      )}
    </>
  )
}
