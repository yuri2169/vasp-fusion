import type { ModelInfo } from '../api/models'
import { Sentences } from '../case/parts'
import { DataTable, type Column } from '../components/DataTable'
import { Panel } from './parts'
import { chainName, count, share } from './words'

type Benchmark = NonNullable<ModelInfo['benchmark']>
type Row = Benchmark['chains'][number]

const mono = 'tabular font-mono text-base'
const n = (v: number | null | undefined) => (v == null ? <span className="text-muted">not measured</span> : <span className={mono}>{count(v)}</span>)

/** "3 of 41 (7.3%; at most 17.6%)": a count is never shown without what it is out of. */
function Wrong({ wrong, named, error, upper }: { wrong?: number | null; named?: number | null; error?: number | null; upper?: number | null }) {
  if (wrong == null || named == null) return <span className="text-muted">not measured</span>
  if (named === 0) return <span className="text-muted">none named</span>
  return (
    <span className={mono}>
      {count(wrong)} of {count(named)}
      {error != null && ` (${share(error)}${upper != null ? `; at most ${share(upper)}` : ''})`}
    </span>
  )
}

const columns: Column<Row>[] = [
  { key: 'chain', header: 'Chain', sortValue: (r) => chainName(r.chain), cell: (r) => <span className="font-medium">{chainName(r.chain)}</span> },
  { key: 'wallets', header: 'Wallets traced', align: 'right', sortValue: (r) => r.wallets ?? null, cell: (r) => n(r.wallets) },
  { key: 'named', header: 'Named', align: 'right', sortValue: (r) => r.named ?? null, cell: (r) => n(r.named) },
  {
    key: 'wrong',
    header: 'Named wrongly',
    align: 'right',
    sortValue: (r) => r.error ?? null,
    cell: (r) => <Wrong wrong={r.wrong} named={r.named} error={r.error} upper={r.error_upper_95} />,
  },
  { key: 'none', header: 'Insufficient evidence', align: 'right', sortValue: (r) => r.not_named ?? null, cell: (r) => n(r.not_named) },
  { key: 'bnamed', header: 'Baseline named', align: 'right', sortValue: (r) => r.baseline_named ?? null, cell: (r) => n(r.baseline_named) },
  {
    key: 'bwrong',
    header: 'Baseline wrongly',
    align: 'right',
    sortValue: (r) => r.baseline_error ?? null,
    cell: (r) => <Wrong wrong={r.baseline_wrong} named={r.baseline_named} error={r.baseline_error} upper={r.baseline_error_upper_95} />,
  },
  {
    key: 'secs',
    header: 'Median seconds',
    align: 'right',
    sortValue: (r) => r.median_seconds ?? null,
    cell: (r) => (r.median_seconds == null ? <span className="text-muted">not recorded</span> : <span className={mono}>{r.median_seconds.toFixed(1)}</span>),
  },
]

/** The benchmark: every chain the tool traces, our answer beside the naive baseline, from
 *  artifacts/benchmark_v1/summary.json as GET /api/model serves it. */
export function BenchmarkTable({ b }: { b: Benchmark }) {
  const hops = b.chains.filter((r) => r.measured && r.by_hops.length > 0)
  return (
    <Panel
      title="Attribution measured on every chain"
      note={`Real wallets that paid a labelled exchange address, traced again with the labels one hop away hidden. Naming bar ${b.bar.toFixed(2)}, seed ${b.seed}. "At most" is a 95% upper bound.`}
    >
      <DataTable caption="Attribution benchmark by chain" columns={columns} rows={b.chains} rowKey={(r) => r.chain} empty="Not yet measured." />
      {hops.length > 0 && (
        <p className="text-sm text-muted" data-testid="benchmark-hops">
          Named, by hops to the exchange:{' '}
          {hops
            .map((r) => `${chainName(r.chain)} ${r.by_hops.map((h) => `${h.hops} ${h.hops === 1 ? 'hop' : 'hops'}: ${count(h.named)} (${count(h.wrong)} wrong)`).join(', ')}`)
            .join('. ')}
          .
        </p>
      )}
      {b.model_gates
        .filter((g) => g.chain !== 'tron')
        .map((g) => (
          <p key={g.chain} className="text-sm text-muted" data-testid={`model-gate-${g.chain}`}>
            <span className="font-medium text-fg">
              The {chainName(g.chain)} deposit-address model is {g.switch_on ? 'used' : 'not used'} when tracing:
            </span>{' '}
            {g.because}. On addresses of an exchange it never saw, {count(g.flagged)} of {count(g.held_out)} scored {g.lead_bar.toFixed(2)} or more, {count(g.flagged_wrong)} of them
            wrongly{g.deposit_addresses_found != null && `; it found ${share(g.deposit_addresses_found)} of the ${count(g.deposit_addresses)} deposit addresses`}.
          </p>
        ))}
      <Sentences items={b.notes} />
    </Panel>
  )
}
