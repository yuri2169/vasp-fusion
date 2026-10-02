import { FolderOpen } from 'lucide-react'
import { useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import type { CaseSummary } from '../api/models'
import { useCases } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { PageHeader } from '../components/PageHeader'
import { formatConfidence, formatDate, formatInr } from '../lib/format'
import { SEARCH_INPUT_ID } from '../shell/GlobalSearch'

const OUTCOME_ORDER = { ATTRIBUTED: 0, SANCTIONED_OR_MIXER_REACHED: 1, INSUFFICIENT_EVIDENCE: 2 }

const columns: Column<CaseSummary>[] = [
  {
    key: 'case',
    header: 'Case',
    sortValue: (c) => c.case_ref ?? c.id,
    cell: (c) => (
      <span className="flex items-center gap-2">
        <span className="font-medium text-fg">{c.case_ref ?? c.id}</span>
        {c.demo && <span className="rounded-sm border border-dashed border-rule-strong px-1 text-xs text-muted">Demo</span>}
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

/** Every case, newest first. U2 adds case intake (reference, complaint number, incident date) and filters. */
export function CasesPage() {
  const cases = useCases()
  const navigate = useNavigate()
  const focusSearch = () => document.getElementById(SEARCH_INPUT_ID)?.focus()

  return (
    <>
      <PageHeader title="Cases">One case per wallet: where its funds went, and which exchange to write to.</PageHeader>
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
          action={
            <Button variant="primary" onClick={focusSearch}>
              Trace a wallet
            </Button>
          }
        >
          Paste a wallet address in the search bar to open the first case. Tron, Bitcoin and EVM wallets can be traced.
        </EmptyState>
      ) : (
        <DataTable
          caption="Cases"
          columns={columns}
          rows={cases.data?.items ?? []}
          rowKey={(c) => c.id}
          loading={cases.isPending}
          initialSort={{ key: 'opened', dir: 'desc' }}
          onRowOpen={(c) => navigate(`/cases/${encodeURIComponent(c.id)}`)}
        />
      )}
    </>
  )
}
