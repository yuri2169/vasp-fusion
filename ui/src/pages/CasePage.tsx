import { lazy, Suspense, useMemo, useRef, useState } from 'react'
import { threatOf } from '../components/ThreatChip'
import type { ThreatTag } from '../api/models'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
import { API_MODE, api } from '../api/api'
import { ApiError } from '../api/client'
import type { CaseDetail, Tier } from '../api/models'
import { useCase, useOpenCase } from '../api/queries'
import { AbstainPanel } from '../case/AbstainPanel'
import { AnswerPanel } from '../case/AnswerPanel'
import { DEFAULT_HOPS } from '../case/rules'
import { TraceAgain } from '../case/TraceAgain'
import { TraceProgress } from '../case/TraceProgress'
import { WalletPanel } from '../case/WalletPanel'
import { AuditTab } from '../case/tabs/AuditTab'
import { InboundTab } from '../case/tabs/InboundTab'
import { PatternsTab } from '../case/tabs/PatternsTab'
import { TimelineTab } from '../case/tabs/TimelineTab'
import { TransfersTab } from '../case/tabs/TransfersTab'
import { WalletsTab } from '../case/tabs/WalletsTab'
import { Button, buttonClass } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { CopyButton } from '../components/CopyButton'
import { ErrorState } from '../components/ErrorState'
import { FundsBar } from '../components/FundsBar'
import { HopRail } from '../components/HopRail'
import { PageHeader } from '../components/PageHeader'
import { ScreeningNote, ThreatChips } from '../components/ThreatChip'
import { Skeleton } from '../components/Skeleton'
import { Tabs, type TabItem } from '../components/Tabs'
import { useToast } from '../components/Toast'
import { buildFlow, pathTo } from '../lib/caseGraph'
import { formatDate, formatInr } from '../lib/format'

// The graph library is half of the interface's code. It is fetched when a case is opened, so the
// list of cases, the sign-in page and the desk paint without it.
const FlowGraph = lazy(() => import('../case/FlowGraph').then((m) => ({ default: m.FlowGraph })))

/** Owners of the labelled wallets in a case, by address, for the Hop Rail's chips. */
function labelsOf(c: CaseDetail): Record<string, { entity: string; tier: Tier; threat?: ThreatTag }> {
  const out: Record<string, { entity: string; tier: Tier; threat?: ThreatTag }> = {}
  for (const node of c.graph.nodes)
    if (node.label) out[node.id] = { entity: node.label.entity, tier: node.label.tier, threat: threatOf(node.label) ?? undefined }
  return out
}

/** The wallets the Hop Rail should mark for a selection: the path from the suspect wallet to it. */
function markedFor(c: CaseDetail, selected: string | null): ReadonlySet<string> {
  if (!selected) return new Set()
  if (selected.startsWith('cluster:')) {
    const name = selected.slice('cluster:'.length)
    return new Set(c.graph.nodes.filter((n) => n.cluster === name).map((n) => n.id))
  }
  return pathTo(buildFlow(c), selected).nodes
}

const TAB_IDS = ['timeline', 'transfers', 'wallets', 'patterns', 'inbound', 'audit'] as const
type TabId = (typeof TAB_IDS)[number]

function Meta({ c }: { c: CaseDetail }) {
  const facts = [
    c.complaint_no && `Complaint ${c.complaint_no}`,
    c.amount_lost_inr != null && `Reported loss ${formatInr(c.amount_lost_inr)}`,
    `Opened ${formatDate(c.created_at)}`,
  ].filter(Boolean) as string[]
  return (
    // Plain running text, so a line that wraps breaks after a separator, never before one.
    <p>
      {facts.map((fact, i) => (
        <span key={fact}>
          <span className="whitespace-nowrap">
            {fact}
            {i < facts.length - 1 && ' ·'}
          </span>{' '}
        </span>
      ))}
      {c.demo && (
        <span title="A real wallet from the demonstration set, traced from recorded chain responses. Verify (in the Audit tab) traces it again and compares." className="ml-1 inline-block rounded-sm border border-dashed border-rule-strong px-1 text-sm text-muted">
          Recorded
        </span>
      )}
    </p>
  )
}

/** A case: the Hop Rail and where the funds went, the fund-flow graph beside the answer
 *  ("Why this exchange?", or why none is named), and the records under them in tabs.
 *  The selected wallet and the open tab are in the address, so a view can be linked to. */
export function CasePage() {
  const { id = '' } = useParams()
  const query = useCase(id)
  const c = query.data
  const location = useLocation()
  const navigate = useNavigate()
  const { show } = useToast()
  const [params, setParams] = useSearchParams()
  const retry = useOpenCase()
  const [asking, setAsking] = useState(false)
  const top = useRef<HTMLDivElement>(null)

  // The rail extends hop by hop only when the result arrived while the officer was watching:
  // they came here from "Trace wallet", or saw the trace running on this page.
  const [watchedTrace, setWatchedTrace] = useState(() => !!(location.state as { watched?: boolean } | null)?.watched)
  const [sawTracing, setSawTracing] = useState(false)
  const tracing = c?.status === 'queued' || c?.status === 'running'
  if (tracing && !sawTracing) setSawTracing(true)

  const selected = params.get('wallet')
  const tab: TabId = TAB_IDS.find((t) => t === params.get('tab')) ?? 'timeline'
  const setParam = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true },
    )
  const select = (wallet: string | null) => setParam('wallet', wallet)
  /** From a tab under the fold: also bring the graph and the panel back into view. */
  const selectFromBelow = (wallet: string) => {
    select(wallet)
    top.current?.scrollIntoView?.({ block: 'start' })
  }

  const marked = useMemo(() => (c ? markedFor(c, selected) : new Set<string>()), [c, selected])

  if (query.isError)
    return (
      <ErrorState
        title="This case could not be opened"
        detail={query.error instanceof ApiError ? query.error.detail : 'Try again.'}
        onRetry={() => void query.refetch()}
      />
    )
  if (!c)
    return (
      <div aria-busy="true" className="flex flex-col gap-6">
        <Skeleton width={320} height={32} />
        <Skeleton height={96} />
        <Skeleton lines={3} />
      </div>
    )

  const hasResult = c.outcome != null
  const candidate = c.candidates.find((x) => x.vasp === c.top_vasp)
  const hops = c.provenance.input?.max_hops ?? DEFAULT_HOPS
  const inbound = c.graph.edges.filter((e) => e.direction === 'inbound').length

  const tabs: TabItem[] = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'transfers', label: 'Transfers', count: c.graph.edges.length },
    { id: 'wallets', label: 'Wallets', count: c.graph.nodes.length },
    { id: 'patterns', label: 'Patterns', count: c.typology_flags.length || undefined },
    { id: 'inbound', label: 'Inbound funding', count: inbound || undefined },
    { id: 'audit', label: 'Audit' },
  ]

  const header = (
    <PageHeader
      eyebrow={`Case ${c.case_ref ?? c.id}`}
      title={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <ChainBadge chain={c.chain} />
          <span className="break-all font-mono text-lg font-medium normal-case tracking-normal">{c.address}</span>
          <CopyButton value={c.address} label="address" />
          <ThreatChips threats={c.threats} />
        </span>
      }
      actions={
        hasResult &&
        !tracing && (
          <>
            {API_MODE === 'live' && (
              <a href={api.caseFileUrl(c.id)} target="_blank" rel="noopener noreferrer" className={buttonClass('secondary')}>
                Case file
              </a>
            )}
            <Button onClick={() => setAsking(true)}>Trace again</Button>
          </>
        )
      }
      meta={<Meta c={c} />}
    />
  )

  if (c.status === 'failed')
    return (
      <>
        {header}
      {c.screening?.hit && (
        <div className="mb-4">
          <ScreeningNote screening={c.screening} />
        </div>
      )}
        <div className="mb-4">
          <ScreeningNote screening={c.screening} />
        </div>
        <ErrorState
          title="The trace failed"
          detail={c.error ?? 'No reason was recorded.'}
        />
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button
            disabled={retry.isPending}
            onClick={() => retry.mutate({ address: c.address, chain: c.chain, max_hops: hops, refresh: true }, { onSuccess: () => setWatchedTrace(true) })}
          >
            {retry.isPending ? 'Starting…' : 'Trace again'}
          </Button>
          {retry.isError && (
            <p role="alert" className="text-base text-seal-text">
              {retry.error instanceof ApiError ? retry.error.detail : 'The trace could not be started. Try again.'}
            </p>
          )}
        </div>
      </>
    )

  const rail = (
    <HopRail
      suspect={{ address: c.address, chain: c.chain }}
      hops={c.hop_rail}
      labels={labelsOf(c)}
      state={tracing && !hasResult ? 'tracing' : 'done'}
      depth={c.progress?.hop ?? 0}
      animate={!tracing && (watchedTrace || sawTracing)}
      selected={selected}
      marked={marked}
      onSelect={hasResult ? select : undefined}
      stamp={{
        outcome: c.outcome ?? null,
        status: hasResult ? 'done' : c.status,
        vasp: c.top_vasp,
        confidence: c.confidence,
        interval: candidate?.confidence_interval,
        whatWouldChange: c.what_would_change?.[0],
      }}
      footer={
        c.where_funds_went && c.where_funds_went.length > 0 ? (
          <FundsBar slices={c.where_funds_went} asset={c.asset ?? ''} total={c.total_sent} named={c.outcome === 'ATTRIBUTED' ? c.top_vasp : null} />
        ) : undefined
      }
    />
  )

  if (!hasResult)
    return (
      <>
        {header}
        <div className="mb-4">
          <ScreeningNote screening={c.screening} />
        </div>
        {rail}
        <TraceProgress
          c={c}
          onStop={() => {
            show({ title: 'Stopped waiting', detail: 'The trace keeps running. Open the case from the list when it is done.' })
            navigate('/cases')
          }}
        />
      </>
    )

  const finished = !tracing && (watchedTrace || sawTracing)

  return (
    <>
      {header}

      {tracing && (
        <p role="status" className="mb-3 rounded border border-dashed border-rule-strong px-3 py-2 text-base text-fg">
          Tracing again. This is the previous result; the new one replaces it when it is ready.
          {c.progress && <span className="mt-1 block text-muted">{c.progress.message}</span>}
        </p>
      )}

      {rail}

      {finished && (
        <p role="status" className="mt-2 text-sm text-muted">
          Trace finished. It read {c.provenance.pages != null ? `${c.provenance.pages} responses` : 'the chain'} and found {c.graph.nodes.length} wallets and{' '}
          {c.graph.edges.length} transfers.
        </p>
      )}

      <div ref={top} className="mt-4 grid scroll-mt-20 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_440px]">
        <Suspense
          fallback={
            <div aria-busy="true" aria-label="Fund-flow graph, loading" className="min-h-[416px] panel p-4">
              <Skeleton width="30%" />
            </div>
          }
        >
          <FlowGraph key={c.id} c={c} selected={selected} onSelect={select} className="lg:sticky lg:top-[76px]" />
        </Suspense>
        {selected ? (
          <WalletPanel c={c} id={selected} onSelect={select} onClose={() => select(null)} />
        ) : c.outcome === 'INSUFFICIENT_EVIDENCE' ? (
          <AbstainPanel c={c} onSelect={select} />
        ) : (
          <AnswerPanel c={c} onSelect={select} />
        )}
      </div>

      <div className="mt-6">
        <Tabs label="Case records" tabs={tabs} active={tab} onChange={(next) => setParam('tab', next === 'timeline' ? null : next)}>
          {tab === 'timeline' && <TimelineTab c={c} onSelect={selectFromBelow} />}
          {tab === 'transfers' && <TransfersTab c={c} onSelect={selectFromBelow} />}
          {tab === 'wallets' && <WalletsTab c={c} selected={selected} onSelect={selectFromBelow} />}
          {tab === 'patterns' && <PatternsTab c={c} onSelect={selectFromBelow} />}
          {tab === 'inbound' && <InboundTab c={c} onSelect={selectFromBelow} />}
          {tab === 'audit' && <AuditTab c={c} />}
        </Tabs>
      </div>

      <TraceAgain c={c} open={asking} onClose={() => setAsking(false)} onStarted={() => setWatchedTrace(true)} />
    </>
  )
}
