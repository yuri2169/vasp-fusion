import { Search } from 'lucide-react'
import { ThreatChip, threatOf, THREATS, THREAT_ORDER } from '../components/ThreatChip'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import type { Category, LabelCoverage, LabelOut, LabelSource, Tier } from '../api/models'
import { useLabelCoverage, useLabelSearch } from '../api/queries'
import { BarList } from '../charts/BarList'
import { AddressChip } from '../components/AddressChip'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { TierTag, TIERS } from '../components/TierTag'
import { formatConfidence, formatPercent } from '../lib/format'
import { Panel } from '../overview/parts'
import { CATEGORY_NAMES, categoryName, chainName, count, isChain, plural } from '../overview/words'

const PAGE = 50
const TIER_ORDER: Tier[] = ['published_por', 'curated', 'explorer_tag', 'derived']
const KIND_WORDS: Record<LabelOut['kind'], string> = {
  deposit: 'Deposit address',
  hot: 'Hot wallet',
  cold: 'Cold wallet',
  reserve: 'Reserve wallet',
  unknown: 'Not stated',
}
const CHAINS_SHOWN = 10

const field = 'h-9 rounded border border-rule-strong bg-surface px-2.5 text-base text-fg'

const columns: Column<LabelOut>[] = [
  {
    key: 'address',
    header: 'Address',
    cell: (l) =>
      isChain(l.chain) ? (
        <span className="flex items-center gap-2">
          <ChainBadge chain={l.chain} size="sm" />
          <AddressChip address={l.address} chain={l.chain} to={`/wallets/${l.chain}/${encodeURIComponent(l.address)}`} />
        </span>
      ) : (
        // A chain the tool cannot trace: the label is held, but there is no wallet page for it.
        <span className="flex items-center gap-2">
          <span className="rounded-sm border border-rule-strong px-1 text-sm uppercase text-muted">{chainName(l.chain)}</span>
          <span className="font-mono text-sm [overflow-wrap:anywhere]" title={l.address}>
            {l.address.length > 20 ? `${l.address.slice(0, 8)}…${l.address.slice(-6)}` : l.address}
          </span>
        </span>
      ),
  },
  {
    key: 'owner',
    header: 'Owner',
    cell: (l) =>
      l.category === 'exchange' && l.entity !== 'Unidentified exchange' ? (
        <Link to={`/vasps/${encodeURIComponent(l.entity)}`} className="font-medium underline decoration-rule-strong underline-offset-2 hover:decoration-current">
          {l.entity}
        </Link>
      ) : (
        <span className="font-medium">{l.entity}</span>
      ),
  },
  {
    key: 'category',
    header: 'Category',
    cell: (l) => (
      <span className="flex flex-wrap items-center gap-1.5 text-base">
        {categoryName(l.category)}
        <ThreatChip tag={threatOf(l)} size="sm" />
      </span>
    ),
  },
  {
    key: 'kind',
    header: 'Kind of wallet',
    cell: (l) => <span className={l.kind === 'unknown' ? 'text-base text-muted' : 'text-base'}>{KIND_WORDS[l.kind]}</span>,
  },
  {
    key: 'tier',
    header: 'Tier',
    cell: (l) => <TierTag tier={l.tier} size="sm" />,
  },
  {
    key: 'confidence',
    header: 'Label confidence',
    align: 'right',
    cell: (l) =>
      l.confidence != null ? (
        <span
          className="tabular whitespace-nowrap font-mono text-base"
          title={l.confidence_low != null ? 'Confirmed by the deposit-address model' : 'Set by the discovery rules, not calibrated'}
        >
          {l.confidence_low == null && <span className="font-sans text-sm text-muted">rule </span>}
          {formatConfidence(l.confidence)}
        </span>
      ) : (
        <span className="text-sm text-muted" title="Only labels this tool derived carry a confidence; a sourced label is as good as its source.">
          as its source
        </span>
      ),
  },
  {
    key: 'source',
    header: 'Source',
    cell: (l) =>
      l.source_url ? (
        <a
          href={l.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-base underline decoration-rule-strong underline-offset-2 [overflow-wrap:anywhere] hover:decoration-current"
        >
          {l.source}
        </a>
      ) : (
        <span className="text-base [overflow-wrap:anywhere]">{l.source}</span>
      ),
  },
]

function Sources({ sources }: { sources: LabelSource[] }) {
  return (
    <div className="overflow-auto rounded border border-rule">
      <table className="w-full border-collapse text-base">
        <caption className="sr-only">Labels per source, with the licence on record</caption>
        <thead>
          <tr className="bg-sunk">
            {['Source', 'Obtained from', 'Licence on record', 'Labels'].map((h, i) => (
              <th key={h} scope="col" className={`eyebrow px-3 py-2 ${i === 3 ? 'text-right' : 'text-left'}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.source} className="border-t border-rule align-top">
              <td className="px-3 py-2">
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-fg underline decoration-rule-strong underline-offset-2 hover:decoration-current">
                    {s.name}
                  </a>
                ) : (
                  <span className="text-fg">{s.name}</span>
                )}
                <span className="mt-1 flex flex-wrap gap-1.5">
                  {TIER_ORDER.filter((t) => s.tiers[t]).map((t) => (
                    <span key={t} className="text-sm text-muted">
                      {TIERS[t].name.toLowerCase()} {count(s.tiers[t])}
                    </span>
                  ))}
                </span>
              </td>
              <td className="px-3 py-2 text-fg">{s.obtained_from ?? <span className="text-muted">Not recorded</span>}</td>
              <td className="px-3 py-2">{s.licence ?? <span className="text-muted">Not recorded</span>}</td>
              <td className="tabular px-3 py-2 text-right font-mono text-fg">{count(s.labels)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** What the label store holds, and what it does not: the counts as they are, with the caveats that follow from them. */
function CoveragePanels({ cov, pick }: { cov: LabelCoverage; pick: (key: string, value: string) => string }) {
  const chains = Object.entries(cov.by_chain).sort((a, b) => b[1] - a[1])
  const rest = chains.slice(CHAINS_SHOWN)
  const [top, topN] = chains[0] ?? ['', 0]
  const categories = Object.entries(cov.by_category).sort((a, b) => b[1] - a[1])
  const unrecorded = (cov.by_source ?? []).filter((s) => s.licence == null).reduce((n, s) => n + s.labels, 0)
  return (
    <div className="grid items-start gap-4 lg:grid-cols-12">
      <Panel title="By tier" className="lg:col-span-4" note="How a label is known. A trace weighs a label by its tier.">
        <BarList
          caption="Labels by tier"
                layer="network"
          labelWidth="12.5rem"
          rows={TIER_ORDER.filter((t) => cov.by_tier[t]).map((t) => ({
            key: t,
            label: <TierTag tier={t} size="sm" />,
            value: cov.by_tier[t],
            valueText: count(cov.by_tier[t]),
            to: pick('tier', t),
          }))}
        />
      </Panel>
      <Panel title="By category" className="lg:col-span-4" note="Who the address belongs to, as its source files it.">
        <BarList
          caption="Labels by category"
                layer="network"
          labelWidth="9.5rem"
          rows={categories.map(([c, n]) => ({
            key: c,
            label: categoryName(c),
            value: n,
            valueText: count(n),
            to: pick('category', c),
          }))}
        />
      </Panel>
      <Panel
        title="By chain"
        className="lg:col-span-4"
        note={top ? `${formatPercent(topN / cov.total)} of all labels are on ${chainName(top)}. Coverage is uneven: a chain with few labels gives few named exchanges.` : undefined}
      >
        <BarList
          caption="Labels by chain"
                layer="network"
          labelWidth="8rem"
          rows={chains.slice(0, CHAINS_SHOWN).map(([c, n]) => ({
            key: c,
            label: chainName(c),
            value: n,
            valueText: count(n),
            to: pick('chain', c),
          }))}
        />
        {rest.length > 0 && (
          <p className="px-1.5 text-sm text-muted">
            and {plural(rest.length, 'more chain')} with {count(rest.reduce((s, [, n]) => s + n, 0))} labels between them
          </p>
        )}
      </Panel>
      {(cov.by_source ?? []).length > 0 && (
        <Panel
          title="By source and licence"
          className="lg:col-span-12"
          note={
            unrecorded > 0
              ? `"Not recorded" means this project holds no record of that source's own licence (${count(unrecorded)} labels): the set they were obtained through releases its code under MIT and leaves each source's data under its upstream licence. Check the source before redistributing.`
              : undefined
          }
        >
          <Sources sources={cov.by_source ?? []} />
        </Panel>
      )}
    </div>
  )
}

/** The labels explorer: search the label store by address or owner, filter by chain, category and
 *  tier, and see how much of each the store covers. The filters live in the address. */
export function LabelsPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const q = params.get('q') ?? ''
  const chain = params.get('chain') ?? ''
  const category = params.get('category') ?? ''
  const tier = params.get('tier') ?? ''
  const threat = params.get('threat') ?? ''
  const offset = Math.max(0, Number(params.get('offset')) || 0)

  const coverage = useLabelCoverage()
  const searching = Boolean(q || chain || category || tier || threat)
  const found = useLabelSearch({ q, chain, category, tier, ...(threat ? { threat } : {}), limit: PAGE, offset }, searching)

  const next = (changes: Record<string, string>) => {
    const p = new URLSearchParams(params)
    p.delete('offset')
    for (const [k, v] of Object.entries(changes))
      if (v) p.set(k, v)
      else p.delete(k)
    return p
  }
  const set = (changes: Record<string, string>) => setParams(next(changes), { replace: true })
  const page = (to: number) => {
    const p = new URLSearchParams(params)
    if (to > 0) p.set('offset', String(to))
    else p.delete('offset')
    setParams(p, { replace: true })
  }
  const pick = (key: string, value: string) => `/labels?${next({ [key]: value }).toString()}`

  const cov = coverage.data
  const chains = cov ? Object.entries(cov.by_chain).sort((a, b) => b[1] - a[1]) : []
  const total = found.data?.total ?? 0

  return (
    <>
      <PageHeader title="Labels">
        The addresses whose owner a source names. A trace can name an exchange only through one of these, so what is missing here is what the tool cannot see.
      </PageHeader>

      <form
        role="search"
        aria-label="Search the label store"
        className="mb-4 flex flex-wrap items-end gap-3 panel p-4"
        onSubmit={(e) => {
          e.preventDefault()
          set({
            q: String(new FormData(e.currentTarget).get('q') ?? '').trim(),
          })
        }}
      >
        <label className="flex min-w-[16rem] flex-1 flex-col gap-1">
          <span className="eyebrow">Address or owner</span>
          <span className="relative">
            <Search size={15} aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 text-muted" />
            <input
              type="search"
              name="q"
              key={q}
              defaultValue={q}
              placeholder="An address from its first character, or a name such as CoinDCX"
              spellCheck={false}
              className={`${field} w-full pl-8 font-mono placeholder:font-sans`}
            />
          </span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="eyebrow">Chain</span>
          <select value={chain} onChange={(e) => set({ chain: e.target.value })} className={field}>
            <option value="">Any chain</option>
            {chains.map(([c, n]) => (
              <option key={c} value={c}>
                {chainName(c)} ({count(n)})
              </option>
            ))}
            {chain && !chains.some(([c]) => c === chain) && <option value={chain}>{chainName(chain)}</option>}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="eyebrow">Category</span>
          <select value={category} onChange={(e) => set({ category: e.target.value })} className={field}>
            <option value="">Any category</option>
            {(Object.keys(CATEGORY_NAMES) as Category[]).map((c) => (
              <option key={c} value={c}>
                {CATEGORY_NAMES[c]}
                {cov?.by_category[c] != null ? ` (${count(cov.by_category[c])})` : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="eyebrow">Tier</span>
          <select value={tier} onChange={(e) => set({ tier: e.target.value })} className={field}>
            <option value="">Any tier</option>
            {TIER_ORDER.map((t) => (
              <option key={t} value={t}>
                {TIERS[t].name}
                {cov?.by_tier[t] != null ? ` (${count(cov.by_tier[t])})` : ''}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="eyebrow">Threat tag</span>
          <select value={threat} onChange={(e) => set({ threat: e.target.value })} className={field}>
            <option value="">Any or none</option>
            <option value="any">Any threat tag</option>
            {THREAT_ORDER.map((t) => (
              <option key={t} value={t}>
                {THREATS[t].name}
                {cov?.by_threat?.[t] != null ? ` (${count(cov.by_threat[t])})` : ''}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="secondary">
          Search labels
        </Button>
        {searching && (
          <Button variant="ghost" onClick={() => navigate('/labels', { replace: true })}>
            Clear
          </Button>
        )}
      </form>

      {searching && (
        <section aria-labelledby="label-results" className="mb-8">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-3">
            <h2 id="label-results" className="eyebrow">
              {found.data ? `${plural(total, 'label')} found` : 'Searching'}
            </h2>
            {total > PAGE && (
              <div className="flex items-center gap-2 text-sm text-muted">
                <span className="tabular">
                  {count(offset + 1)} to {count(Math.min(offset + PAGE, total))} of {count(total)}
                </span>
                <Button size="sm" disabled={offset === 0} onClick={() => page(offset - PAGE)}>
                  Previous
                </Button>
                <Button size="sm" disabled={offset + PAGE >= total} onClick={() => page(offset + PAGE)}>
                  Next
                </Button>
              </div>
            )}
          </div>
          {found.isError ? (
            <ErrorState
              title="The labels could not be searched"
              detail={found.error instanceof ApiError ? found.error.detail : 'Try again.'}
              onRetry={() => void found.refetch()}
            />
          ) : (
            <DataTable
              caption="Labels found"
              columns={columns}
              rows={found.data?.items ?? []}
              rowKey={(l) => `${l.chain}:${l.address}`}
              loading={found.isPending}
              empty="No label matches. An address with no label is not known to be clean: no source names its owner."
            />
          )}
        </section>
      )}

      <h2 className="eyebrow mb-2">What the store covers</h2>
      {coverage.isError ? (
        <ErrorState
          title="The coverage could not be loaded"
          detail={coverage.error instanceof ApiError ? coverage.error.detail : 'Try again.'}
          onRetry={() => void coverage.refetch()}
        />
      ) : cov ? (
        <>
          <p className="mb-3 max-w-prose text-base text-muted">
            <span className="tabular font-mono text-fg">{count(cov.total)}</span> labelled addresses
            {cov.traceable_total != null && cov.traceable_total < cov.total && (
              <>
                , <span className="tabular font-mono text-fg">{count(cov.traceable_total)}</span> of them on chains this tool can trace
              </>
            )}
            . Every count below opens the labels behind it.
          </p>
          <CoveragePanels cov={cov} pick={pick} />
        </>
      ) : (
        <p className="text-base text-muted" aria-busy="true">
          Counting the labels…
        </p>
      )}
    </>
  )
}
