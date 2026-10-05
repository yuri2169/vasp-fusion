import type { ScaleMetrics, ScaleRun } from '../api/models'
import { useScale } from '../api/queries'
import { Sentences } from '../case/parts'
import { DataTable, type Column } from '../components/DataTable'
import { Skeleton } from '../components/Skeleton'
import { formatNumber } from '../lib/format'
import { Panel } from './parts'

const one = (v: number) => v.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const two = (v: number) => v.toFixed(2)

function columns(best: number): Column<ScaleRun>[] {
  return [
    { key: 'workers', header: 'Worker processes', align: 'right', width: 130, cell: (r) => <span className="tabular font-mono">{r.workers}</span> },
    {
      key: 'rate',
      header: 'Cases per minute',
      cell: (r) => (
        <span className="flex items-center gap-3">
          <span className="tabular w-16 shrink-0 text-right font-mono text-ink">{one(r.cases_per_minute)}</span>
          {/* the bar encodes the same figure: its length against the fastest run */}
          <span aria-hidden className="h-2.5 flex-1 bg-surface-3">
            <span className="anim-bar block h-full bg-ink" style={{ width: `${(r.cases_per_minute / best) * 100}%` }} />
          </span>
        </span>
      ),
    },
    { key: 'speedup', header: 'Against one worker', align: 'right', width: 130, cell: (r) => <span className="tabular font-mono">×{two(r.speedup)}</span> },
    { key: 'median', header: 'Median s per case', align: 'right', width: 130, cell: (r) => <span className="tabular font-mono">{two(r.median_seconds_per_case)}</span> },
    { key: 'p95', header: '95th percentile s', align: 'right', width: 130, cell: (r) => <span className="tabular font-mono">{two(r.p95_seconds_per_case)}</span> },
    { key: 'transfers', header: 'Transfers per second', align: 'right', width: 140, cell: (r) => <span className="tabular font-mono">{formatNumber(Math.round(r.transfers_per_second))}</span> },
    {
      key: 'memory',
      header: 'Peak memory',
      align: 'right',
      width: 120,
      cell: (r) => (r.peak_memory_mb != null ? <span className="tabular font-mono">{formatNumber(Math.round(r.peak_memory_mb))} MB</span> : <span className="text-ink-dim">-</span>),
    },
  ]
}

type Before = { cases_per_minute?: number; median_seconds_per_case?: number; commit?: string }
type Intake = { rows?: number; seconds?: number; rows_per_second?: number }

/** What was measured, in the file's own figures. Nothing here is typed in. */
export function ThroughputFigures({ m }: { m: ScaleMetrics }) {
  const best = Math.max(...m.runs.map((r) => r.cases_per_minute), 1)
  const cases = m.runs[0]?.cases
  const before = m.baseline as Before | null | undefined
  const intake = m.intake as Intake | null | undefined
  const golden = m.runs.every((r) => r.golden_fingerprints_reproduced === `${r.cases} of ${r.cases}`)
  return (
    <>
      <DataTable caption="Throughput by number of worker processes" columns={columns(best)} rows={m.runs} rowKey={(r) => String(r.workers)} empty="Not yet measured." />
      <ul className="flex flex-col gap-1 text-base text-ink">
        {cases != null && (
          <li>
            Each run traced {formatNumber(cases)} cases: {m.wallets} recorded wallets, {m.rounds} times each.{' '}
            {golden ? 'Every case, at every worker count, has the findings fingerprint the repository records for its wallet.' : 'Not every case reproduced its recorded fingerprint; see the file.'}
          </li>
        )}
        {before?.cases_per_minute != null && (
          <li>
            Before the queue and the pool, the same replay in one process ran at <span className="tabular font-mono">{one(before.cases_per_minute)}</span> cases per minute
            {before.median_seconds_per_case != null && (
              <>
                {' '}
                (median <span className="tabular font-mono">{two(before.median_seconds_per_case)}</span> s per case)
              </>
            )}
            .
          </li>
        )}
        {intake?.rows != null && intake.seconds != null && (
          <li>
            A batch upload of {formatNumber(intake.rows)} addresses was checked and queued in <span className="tabular font-mono">{two(intake.seconds)}</span> s.
          </li>
        )}
      </ul>
      {m.limits.length > 0 && (
        <div>
          <h3 className="eyebrow mb-2">What limits it, and what was not measured</h3>
          <Sentences items={m.limits} />
        </div>
      )}
      <p className="border-t border-rule pt-2 text-sm text-ink-soft">
        Measured {m.measured_on} on {m.machine}. Chain data: {m.chain_data}. Run <code className="font-mono text-ink">make bench-scale</code> to measure it on this machine.
      </p>
    </>
  )
}

/** Large-volume tracing, as measured: read from the file `make bench-scale` writes, or "not measured". */
export function Throughput() {
  const q = useScale()
  const m = q.data
  return (
    <Panel
      title="Throughput: wallets traced per minute"
      note="A batch of wallets is queued and traced by a pool of worker processes. These are the figures of one run on one machine, with chain responses replayed from a cache."
    >
      {q.isPending ? (
        <Skeleton lines={4} />
      ) : q.isError || !m ? (
        <p className="text-base text-ink">The measured figures could not be read. Reload the page to try again.</p>
      ) : m.status !== 'measured' ? (
        <p className="text-base text-ink">
          Not yet measured on this installation, so no figure is shown. Run <code className="font-mono">make bench-scale</code> to measure it.
        </p>
      ) : (
        <ThroughputFigures m={m} />
      )}
    </Panel>
  )
}
