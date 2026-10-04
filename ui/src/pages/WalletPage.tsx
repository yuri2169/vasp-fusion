import { Eye, EyeOff, OctagonAlert, ShieldQuestion, TriangleAlert, type LucideIcon } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import type { Chain, FlowSummary, WalletDetail } from '../api/models'
import { useCases, useOpenCase, useUnwatch, useWallet, useWatch } from '../api/queries'
import { LabelBlock } from '../case/WalletPanel'
import { ROLE_NAMES } from '../case/caseText'
import { Sentences } from '../case/parts'
import { AddressChip } from '../components/AddressChip'
import { Button, buttonClass } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { CopyButton } from '../components/CopyButton'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { addressUrl, explorerName } from '../lib/explorers'
import { Rupees, usdOf } from '../components/Rupees'
import { formatAmount, formatDate, formatUsd } from '../lib/format'
import { Panel } from '../overview/parts'
import { isChain, plural } from '../overview/words'

type Level = NonNullable<WalletDetail['risk']['level']> | 'unassessed'
type CaseRef = WalletDetail['cases'][number]

const LEVELS: Record<Level, { words: string; Icon: LucideIcon; look: string; says: string }> = {
  high: {
    words: 'High',
    Icon: OctagonAlert,
    look: 'border-seal-text text-seal-text',
    says: 'A sanctions, mixer or scam label, or an alert of a case, names this address.',
  },
  elevated: {
    words: 'Elevated',
    Icon: TriangleAlert,
    look: 'border-rule-strong text-fg',
    says: 'A pattern in a case names this address, or funds it sent reached a sanctioned address or a mixer.',
  },
  none: {
    words: 'Nothing on record',
    Icon: ShieldQuestion,
    look: 'border-dashed border-rule-strong text-muted',
    says: 'No label and no case holds anything against this address. That is not a clearance: it says only what is on file here.',
  },
  unassessed: {
    words: 'Not assessed',
    Icon: ShieldQuestion,
    look: 'border-dashed border-rule-strong text-muted',
    says: 'This address has no label and is in no case, so there is nothing to assess it on. Trace it to find out more.',
  },
}

function Flow({ title, flow, chain, empty }: { title: string; flow: FlowSummary | null | undefined; chain: Chain; empty: string }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-base font-semibold text-fg">{title}</h3>
      {!flow ? (
        <p className="text-base text-muted">{empty}</p>
      ) : (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-base">
            <dt className="text-muted">Transfers</dt>
            <dd className="tabular font-mono text-fg">{flow.tx_count.toLocaleString('en-US')}</dd>
            <dt className="text-muted">Total</dt>
            <dd className="tabular font-mono text-fg">
              {flow.total != null && flow.asset ? formatAmount(flow.total, flow.asset) : flow.total_usd != null ? formatUsd(flow.total_usd) : 'in more than one asset'}
              <Rupees usd={flow.total_usd ?? (flow.total != null && flow.asset ? usdOf(flow.total, flow.asset) : null)} />
            </dd>
            {flow.first_seen && flow.last_seen && (
              <>
                <dt className="text-muted">Between</dt>
                <dd className="tabular text-fg">
                  {formatDate(flow.first_seen)}
                  {formatDate(flow.last_seen) !== formatDate(flow.first_seen) && ` and ${formatDate(flow.last_seen)}`}
                </dd>
              </>
            )}
            {flow.counterparties != null && (
              <>
                <dt className="text-muted">Other wallets</dt>
                <dd className="tabular font-mono text-fg">{flow.counterparties.toLocaleString('en-US')}</dd>
              </>
            )}
          </dl>
          {flow.top_counterparties.length > 0 && (
            <ul aria-label={`${title}: largest counterparties`} className="flex flex-col gap-1.5 border-t border-rule pt-2">
              {flow.top_counterparties.map((a) => (
                <li key={a}>
                  <AddressChip address={a} chain={chain} to={`/wallets/${chain}/${encodeURIComponent(a)}`} actions="copy" />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

/** Everything on record about one address: its label, what is held against it, the cases it is in,
 *  and the transfers those cases read of it. */
export function WalletPage() {
  const { chain = '', address = '' } = useParams()
  const valid = isChain(chain)
  const wallet = useWallet(valid ? chain : 'tron', valid ? address : '')
  const cases = useCases()
  const openCase = useOpenCase()
  const watch = useWatch()
  const unwatch = useUnwatch()
  const toast = useToast()
  const navigate = useNavigate()

  if (!valid)
    return (
      <>
        <PageHeader eyebrow="Wallet" title="Unknown chain" />
        <EmptyState title={`"${chain}" is not a chain this tool knows`}>Open a wallet from a case, the labels explorer or the search bar.</EmptyState>
      </>
    )

  const w = wallet.data
  const label = w?.labels[0]
  const refOf = (id: string) => cases.data?.items.find((c) => c.id === id)?.case_ref ?? id
  const own = w?.cases.find((c) => c.role === 'suspect')
  const level: Level = w?.risk.level ?? 'unassessed'
  const look = LEVELS[level]
  const failed = (title: string) => (e: unknown) =>
    toast.show({
      kind: 'error',
      title,
      detail: e instanceof ApiError ? e.detail : undefined,
    })

  const trace = () =>
    openCase.mutate(
      { address, chain },
      {
        onSuccess: (c) => navigate(`/cases/${encodeURIComponent(c.id)}`),
        onError: failed('The wallet could not be traced'),
      },
    )
  const toggleWatch = () =>
    w?.watched
      ? unwatch.mutate(`${chain}-${address}`, {
          onSuccess: () => toast.show({ kind: 'success', title: 'Stopped watching' }),
          onError: failed('Still on the watchlist'),
        })
      : watch.mutate(
          { address, chain },
          {
            onSuccess: () => toast.show({ kind: 'success', title: 'Watching this wallet' }),
            onError: failed('The wallet is not being watched'),
          },
        )

  const caseColumns: Column<CaseRef>[] = [
    {
      key: 'case',
      header: 'Case',
      sortValue: (c) => refOf(c.case_id),
      cell: (c) => (
        <Link
          to={`/cases/${encodeURIComponent(c.case_id)}?wallet=${encodeURIComponent(address)}`}
          className="font-medium underline decoration-rule-strong underline-offset-2 hover:decoration-current"
        >
          {refOf(c.case_id)}
        </Link>
      ),
    },
    {
      key: 'role',
      header: 'Its part in the case',
      cell: (c) => <span className="text-base">{ROLE_NAMES[c.role]}</span>,
    },
    {
      key: 'hop',
      header: 'Hops from the traced wallet',
      align: 'right',
      sortValue: (c) => c.hop,
      cell: (c) => <span className="tabular font-mono text-base">{c.hop === 0 ? 'the traced wallet' : c.hop}</span>,
    },
  ]

  return (
    <>
      <PageHeader
        eyebrow="Wallet"
        title={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <ChainBadge chain={chain} />
            <span className="font-mono text-lg font-medium normal-case tracking-normal [overflow-wrap:anywhere]">{address}</span>
            <CopyButton value={address} label="Copy the address" />
          </span>
        }
        meta={
          <a href={addressUrl(chain, address)} target="_blank" rel="noopener noreferrer" className="underline decoration-rule-strong underline-offset-2 hover:decoration-current">
            Open on {explorerName(chain)}
          </a>
        }
        actions={
          <>
            <Button
              onClick={toggleWatch}
              disabled={!w || watch.isPending || unwatch.isPending}
              icon={w?.watched ? <EyeOff size={15} aria-hidden /> : <Eye size={15} aria-hidden />}
            >
              {w?.watched ? 'Stop watching' : 'Watch this wallet'}
            </Button>
            {own ? (
              <Link to={`/cases/${encodeURIComponent(own.case_id)}`} className={buttonClass('secondary')}>
                Open its case
              </Link>
            ) : (
              <Button variant="primary" onClick={trace} disabled={!CHAINS[chain].traceable || openCase.isPending} title={CHAINS[chain].whyNot}>
                Trace this wallet
              </Button>
            )}
          </>
        }
      />

      {wallet.isError ? (
        <ErrorState title="This wallet could not be loaded" detail={wallet.error instanceof ApiError ? wallet.error.detail : 'Try again.'} onRetry={() => void wallet.refetch()} />
      ) : !w ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton width="40%" />
          <Skeleton width="70%" />
        </div>
      ) : (
        <div className="grid items-start gap-4 lg:grid-cols-12">
          <div className="flex flex-col gap-4 lg:col-span-5">
            <div className="panel p-4">
              {label ? (
                <>
                  <LabelBlock label={label} chain={chain} />
                  {label.category !== 'sanctioned' && label.entity !== 'Unidentified exchange' && (
                    <Link
                      to={`/vasps/${encodeURIComponent(label.entity)}`}
                      className="mt-3 inline-block text-sm text-muted underline decoration-rule-strong underline-offset-2 hover:text-fg"
                    >
                      Everything on file about {label.entity}
                    </Link>
                  )}
                </>
              ) : (
                <section aria-label="Label" className="flex flex-col gap-2">
                  <h2 className="eyebrow">Label</h2>
                  <p className="text-base text-fg">No label. None of the label sources names the owner of this address.</p>
                </section>
              )}
            </div>

            <Panel title="On record against this address">
              <p className={cx('inline-flex w-fit items-center gap-1.5 rounded-sm border px-2 py-1 text-base font-semibold', look.look)}>
                <look.Icon size={15} aria-hidden />
                {look.words}
              </p>
              {w.risk.reasons.length > 0 ? <Sentences items={w.risk.reasons} /> : <p className="text-base text-fg">{look.says}</p>}
              <p className="border-t border-rule pt-2 text-sm text-muted">
                No risk score is computed. The level is a plain rule over this address's label and the patterns of the stored cases; the sentences above are what it rests on.
              </p>
            </Panel>
          </div>

          <div className="flex flex-col gap-4 lg:col-span-7">
            <section aria-labelledby="wallet-cases">
              <h2 id="wallet-cases" className="eyebrow mb-2">
                In cases
              </h2>
              <DataTable
                caption="Cases this address appears in"
                columns={caseColumns}
                rows={w.cases}
                rowKey={(c) => c.case_id}
                empty="This address is in no case yet. Trace it, or it will appear here when a trace passes through it."
              />
            </section>

            <Panel
              title="Transfers the cases read"
              note={
                w.flows_from_cases
                  ? `Read from ${plural(w.flows_from_cases, 'stored case')}: the transfers those traces followed, each counted once. This is not the wallet's whole history.`
                  : 'Only transfers that a stored trace followed are counted here, never the wallet’s whole history.'
              }
            >
              <div className="grid gap-6 sm:grid-cols-2">
                <Flow title="Coming in" flow={w.inbound} chain={chain} empty="No case read a transfer into this address." />
                <Flow title="Going out" flow={w.outbound} chain={chain} empty="No case read a transfer out of this address." />
              </div>
            </Panel>
          </div>
        </div>
      )}
    </>
  )
}
