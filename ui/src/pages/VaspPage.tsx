import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import type { Chain, RequestSummary, VaspWallet } from '../api/models'
import { useCases, useDesk, useVasp } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { Button, buttonClass } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { TierTag } from '../components/TierTag'
import { DirectoryFacts } from '../desk/DirectoryFacts'
import { DraftDialog } from '../desk/DraftDialog'
import { StatusTag } from '../desk/StatusTag'
import { isOverdue } from '../desk/status'
import { CHAINS } from '../lib/chains'
import { Rupees } from '../components/Rupees'
import { formatConfidence, formatDate, formatUsd } from '../lib/format'

const isChain = (chain: string): chain is Chain => chain in CHAINS

/** An exchange: what is on file about it (cited), its wallets across every case, and the requests made to it. */
export function VaspPage() {
  const { name = '' } = useParams()
  const page = useVasp(name)
  const desk = useDesk()
  const cases = useCases()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()

  if (page.isError)
    return (
      <>
        <PageHeader eyebrow={<Link to="/desk">Request desk</Link>} title={name} />
        <ErrorState
          title="This exchange could not be loaded"
          detail={page.error instanceof ApiError ? (page.error.status === 404 ? `Nothing is on file for "${name}": no label, no directory entry, no case.` : page.error.detail) : 'Try again.'}
          onRetry={() => void page.refetch()}
        />
      </>
    )

  const data = page.data
  const directory = data?.directory
  const title = directory?.name ?? name
  const refOf = (id: string) => cases.data?.items.find((c) => c.id === id)?.case_ref ?? id

  const row = desk.data?.rows.find((r) => r.vasp === title)
  const routable = (data?.wallets ?? []).filter((w) => w.routable !== false)
  // The desk knows whether a request already asks about every wallet; without its row, offer the draft and let the server say.
  const canDraft = routable.length > 0 && (!row || row.status === 'not_requested' || (row.unrequested_wallets ?? 0) > 0)
  const counts = Object.entries(data?.label_counts ?? {}).sort((a, b) => b[1] - a[1])

  const walletColumns: Column<VaspWallet>[] = [
    {
      key: 'wallet',
      header: 'Wallet',
      cell: (w) => (
        <span className="flex items-center gap-2">
          {isChain(w.chain) ? (
            <>
              <ChainBadge chain={w.chain} size="sm" />
              <AddressChip address={w.address} chain={w.chain} />
            </>
          ) : (
            <span className="font-mono text-sm">{w.address}</span>
          )}
        </span>
      ),
    },
    {
      key: 'case',
      header: 'Case',
      sortValue: (w) => (w.case_id ? refOf(w.case_id) : null),
      cell: (w) =>
        w.case_id ? (
          <Link to={`/cases/${encodeURIComponent(w.case_id)}`} className="whitespace-nowrap text-base underline decoration-rule-strong underline-offset-2 hover:decoration-current">
            {refOf(w.case_id)}
          </Link>
        ) : (
          <span className="text-muted">none</span>
        ),
    },
    {
      key: 'direction',
      header: 'Direction',
      cell: (w) => <span className="text-base">{w.direction === 'inbound' ? 'It funded the wallet' : 'The funds went there'}</span>,
    },
    {
      key: 'usd',
      header: 'Traced, USD',
      align: 'right',
      sortValue: (w) => w.amount_usd ?? null,
      cell: (w) =>
        w.amount_usd != null ? <span className="tabular whitespace-nowrap font-mono text-base font-medium">{formatUsd(w.amount_usd)}<Rupees usd={w.amount_usd} className="ml-2 font-normal text-muted" /></span> : <span className="text-muted">not in USD</span>,
    },
    { key: 'tier', header: 'Evidence tier', cell: (w) => <TierTag tier={w.tier} size="sm" /> },
    {
      key: 'confidence',
      header: 'Confidence',
      align: 'right',
      sortValue: (w) => w.confidence ?? null,
      cell: (w) => (w.confidence != null ? <span className="tabular font-mono text-base">{formatConfidence(w.confidence)}</span> : <span className="text-muted">none</span>),
    },
    {
      key: 'request',
      header: 'In a request',
      cell: (w) =>
        w.routable === false ? (
          <span
            title="Under the 0.60 naming bar, the exchange's own wallet, or the exchange funded the wallet. No request can be drafted on it."
            className="inline-flex h-6 items-center rounded-sm border border-dashed border-rule-strong px-1.5 text-sm text-muted"
          >
            Context only
          </span>
        ) : (
          <span className="text-base">Can be requested</span>
        ),
    },
  ]

  const requestColumns: Column<RequestSummary>[] = [
    { key: 'ref', header: 'Reference', sortValue: (r) => r.reference, cell: (r) => <span className="font-mono text-base font-medium">{r.reference}</span> },
    { key: 'status', header: 'Status', cell: (r) => <StatusTag status={r.status} /> },
    { key: 'cases', header: 'Cases', cell: (r) => <span className="text-base">{r.case_ids.map(refOf).join(', ')}</span> },
    {
      key: 'drafted',
      header: 'Drafted',
      align: 'right',
      sortValue: (r) => r.created_at,
      cell: (r) => <span className="tabular whitespace-nowrap text-base text-muted">{formatDate(r.created_at)}</span>,
    },
    {
      key: 'due',
      header: 'Reply due',
      align: 'right',
      sortValue: (r) => r.due ?? null,
      cell: (r) =>
        r.due ? (
          <span className={isOverdue(r) ? 'tabular whitespace-nowrap text-base font-medium text-seal-text' : 'tabular whitespace-nowrap text-base text-muted'}>
            {formatDate(r.due)}
            {isOverdue(r) && ', overdue'}
          </span>
        ) : (
          <span className="text-muted">not sent</span>
        ),
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow={<Link to="/desk">Request desk</Link>}
        title={title}
        meta={directory ? (directory.legal_name ?? 'No legal name on file') : undefined}
        actions={
          canDraft ? (
            <Button variant="primary" onClick={() => setParams({ draft: '1' })}>
              Draft request to {title}
            </Button>
          ) : row?.last_request_id ? (
            <Link to={`/requests/${encodeURIComponent(row.last_request_id)}`} className={buttonClass('secondary')}>
              Open request
            </Link>
          ) : undefined
        }
      />

      {!data || !directory ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton width="40%" />
          <Skeleton width="70%" />
          <Skeleton width="55%" />
        </div>
      ) : (
        <div className="flex flex-col gap-8">
          <section aria-labelledby="on-file">
            <h2 id="on-file" className="eyebrow mb-2">
              On file, with sources
            </h2>
            <DirectoryFacts directory={directory} />
            {counts.length > 0 && (
              <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
                <span>Labelled addresses in the label store:</span>
                {counts.map(([chain, n]) => (
                  <span key={chain} className="tabular whitespace-nowrap font-mono">
                    {isChain(chain) ? CHAINS[chain].code : chain.toUpperCase()} {n.toLocaleString('en-US')}
                  </span>
                ))}
              </p>
            )}
          </section>

          <section aria-labelledby="its-wallets">
            <h2 id="its-wallets" className="eyebrow mb-2">
              Wallets in cases
            </h2>
            <DataTable
              caption={`Wallets of ${title} in cases`}
              columns={walletColumns}
              rows={data.wallets}
              rowKey={(w) => `${w.case_id}:${w.address}:${w.direction}`}
              empty={`No case has reached a wallet of ${title} yet.`}
            />
          </section>

          <section aria-labelledby="its-requests">
            <h2 id="its-requests" className="eyebrow mb-2">
              Request history
            </h2>
            <DataTable
              caption={`Requests to ${title}`}
              columns={requestColumns}
              rows={data.requests}
              rowKey={(r) => r.id}
              initialSort={{ key: 'drafted', dir: 'desc' }}
              onRowOpen={(r) => navigate(`/requests/${encodeURIComponent(r.id)}`)}
              empty={`No request has been drafted to ${title}.`}
            />
          </section>
        </div>
      )}
      {params.get('draft') && <DraftDialog vasp={title} onClose={() => setParams({}, { replace: true })} />}
    </>
  )
}
