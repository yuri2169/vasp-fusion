import { Link, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import type { ModelInfo } from '../api/models'
import { useModel } from '../api/queries'
import { BarList } from '../charts/BarList'
import { CoveragePlot, ReliabilityPlot } from '../charts/ModelPlots'
import { Sentences } from '../case/parts'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { cx } from '../lib/cx'
import { formatDate, formatPercent } from '../lib/format'
import { BenchmarkTable } from '../overview/BenchmarkTable'
import { Ledger, Panel, type LedgerEntry } from '../overview/parts'
import { Throughput } from '../overview/Throughput'
import { count, plural, score, share } from '../overview/words'

const CHAINS = [
  { id: 'tron', name: 'Tron', says: 'the model whose scores the labels carry' },
  {
    id: 'ethereum',
    name: 'Ethereum',
    says: 'the same model measured against explorer tags our rules never saw',
  },
]

type Fold = ModelInfo['leave_one_exchange_out'][number]
type Bar = NonNullable<ModelInfo['abstain']>['bars'][number]

const pct = (v: number | null | undefined) => (v == null ? 'not measured' : share(v))
const mono = 'tabular font-mono text-base'

const foldColumns: Column<Fold>[] = [
  {
    key: 'exchange',
    header: 'Exchange held out',
    sortValue: (f) => f.exchange,
    cell: (f) => <span className="font-medium">{f.exchange}</span>,
  },
  {
    key: 'n',
    header: 'Addresses',
    align: 'right',
    sortValue: (f) => f.n,
    cell: (f) => <span className={mono}>{count(f.n)}</span>,
  },
  {
    key: 'pos',
    header: 'Deposit addresses',
    align: 'right',
    sortValue: (f) => f.n_positive,
    cell: (f) => <span className={mono}>{count(f.n_positive)}</span>,
  },
  {
    key: 'pr',
    header: 'PR-AUC',
    align: 'right',
    sortValue: (f) => f.pr_auc ?? null,
    cell: (f) => <span className={mono}>{score(f.pr_auc)}</span>,
  },
  {
    key: 'precision',
    header: 'Precision',
    align: 'right',
    sortValue: (f) => f.precision ?? null,
    cell: (f) => <span className={mono}>{score(f.precision)}</span>,
  },
  {
    key: 'recall',
    header: 'Recall',
    align: 'right',
    sortValue: (f) => f.recall ?? null,
    // A model that finds under half of an unseen exchange's addresses has not carried over: say so in the cell.
    cell: (f) => <span className={cx(mono, f.recall != null && f.recall < 0.5 && 'font-semibold text-seal-text')}>{score(f.recall)}</span>,
  },
  {
    key: 'ece',
    header: 'Calibration error',
    align: 'right',
    sortValue: (f) => f.ece ?? null,
    cell: (f) => <span className={mono}>{score(f.ece)}</span>,
  },
]

function headline(m: ModelInfo): LedgerEntry[] {
  const k = m.metrics
  return [
    {
      key: 'n',
      name: 'Test addresses',
      value: k.n_test != null ? count(k.n_test) : 'not measured',
      note: 'the latest 20%, never trained on',
    },
    {
      key: 'pr',
      name: 'PR-AUC',
      value: score(k.pr_auc),
      note: 'ranking: 1 is perfect',
    },
    {
      key: 'brier',
      name: 'Brier score',
      value: score(k.brier),
      note: 'probability error: 0 is perfect',
    },
    {
      key: 'ece',
      name: 'Calibration error',
      value: score(k.ece),
      note: 'gap between given and observed',
    },
    {
      key: 'cov',
      name: 'Sure about',
      value: pct(k.coverage),
      note: 'probability at least 0.9 either way',
    },
    {
      key: 'acc',
      name: 'Right when sure',
      value: pct(k.accuracy_when_answering),
      note: 'on those addresses',
    },
  ]
}

function Abstain({ a }: { a: NonNullable<ModelInfo['abstain']> }) {
  const columns: Column<Bar>[] = [
    {
      key: 'bar',
      header: 'Naming bar',
      sortValue: (b) => b.threshold,
      cell: (b) => (
        <span className={mono}>
          {b.threshold.toFixed(2)}
          {b.threshold === a.current_threshold && <span className="ml-2 rounded-sm border border-fg px-1 font-sans text-sm font-semibold">in use</span>}
        </span>
      ),
    },
    {
      key: 'named',
      header: 'Wallets named',
      align: 'right',
      sortValue: (b) => b.wallets_named,
      cell: (b) => <span className={mono}>{count(b.wallets_named)}</span>,
    },
    {
      key: 'wrong',
      header: 'Named wrongly',
      align: 'right',
      sortValue: (b) => b.wallets_wrong,
      cell: (b) => <span className={mono}>{count(b.wallets_wrong)}</span>,
    },
    {
      key: 'risk',
      header: 'Share wrong',
      align: 'right',
      sortValue: (b) => b.risk ?? null,
      cell: (b) => <span className={mono}>{b.risk != null ? share(b.risk) : 'none named'}</span>,
    },
    {
      key: 'bound',
      header: 'At most (upper bound)',
      align: 'right',
      sortValue: (b) => b.risk_upper_bound ?? null,
      cell: (b) => <span className={mono}>{b.risk_upper_bound != null ? share(b.risk_upper_bound) : 'not measured'}</span>,
    },
    {
      key: 'abstain',
      header: 'No exchange named',
      align: 'right',
      sortValue: (b) => b.wallets_abstained,
      cell: (b) => <span className={mono}>{count(b.wallets_abstained)}</span>,
    },
  ]
  return (
    <Panel
      title={`The ${a.current_threshold.toFixed(2)} naming bar, checked`}
      note={`${plural(a.wallets, 'real wallet')} traced with the derived labels hidden, giving ${plural(a.claims, 'claim')} with a known answer. The target was at most ${formatPercent(a.target_risk)} wrong.`}
    >
      <p className="text-base text-fg">
        {a.measured_threshold != null
          ? `The lowest bar that keeps the share wrong under the target is ${a.measured_threshold.toFixed(2)}.`
          : `No bar brings the upper bound under ${formatPercent(a.target_risk)}, so this measurement does not choose a bar. The bar in use, ${a.current_threshold.toFixed(2)}, is a rule that was checked, not one that was calibrated.`}
      </p>
      <DataTable caption="Each candidate naming bar on the hold-out wallets" columns={columns} rows={a.bars} rowKey={(b) => String(b.threshold)} />
      <div className="grid items-start gap-6 border-t border-rule pt-3 lg:grid-cols-2">
        {a.risk_coverage.length > 1 && (
          <div>
            <h3 className="eyebrow mb-2">Right when answering, against claims answered</h3>
            <CoveragePlot
              points={a.risk_coverage}
              caption="Claims that were right against the share of claims answered"
              xTitle="Share of claims answered (surest first)"
              yTitle="Right when answering"
            />
          </div>
        )}
        {a.notes.length > 0 && (
          <div>
            <h3 className="eyebrow mb-2">What this check does not show</h3>
            <Sentences items={a.notes} />
          </div>
        )}
      </div>
    </Panel>
  )
}

/** How the deposit-address model was measured: calibration, accuracy when it answers, what it reads,
 *  how it does on an exchange it never saw, and what the numbers do not say. Nothing here is a placeholder. */
export function ModelPage() {
  const [params, setParams] = useSearchParams()
  const chain = CHAINS.some((c) => c.id === params.get('chain')) ? params.get('chain')! : 'tron'
  const model = useModel(chain)
  const m = model.data
  const about = CHAINS.find((c) => c.id === chain)!

  const switcher = (
    <div role="group" aria-label="Measured on" className="flex gap-1.5">
      {CHAINS.map((c) => (
        <button
          key={c.id}
          type="button"
          aria-pressed={c.id === chain}
          onClick={() => setParams(c.id === 'tron' ? {} : { chain: c.id }, { replace: true })}
          className={cx(
            'inline-flex h-9 items-center rounded border px-3 text-base',
            c.id === chain ? 'border-fg bg-fg font-semibold text-page' : 'border-rule-strong bg-surface text-fg hover:bg-sunk',
          )}
        >
          {c.name}
        </button>
      ))}
    </div>
  )

  return (
    <>
      <PageHeader
        title="Deposit-address model"
        actions={switcher}
        meta={
          m?.status === 'measured' ? (
            <>
              {m.version} · trained {m.trained_at ? formatDate(m.trained_at) : 'date not recorded'} · split {m.split} · {about.name}: {about.says}
            </>
          ) : undefined
        }
      >
        A model that reads how an address behaves and says how likely it is an exchange's deposit address. It confirms labels and raises leads; it never names an exchange by
        itself.
      </PageHeader>

      {model.data?.benchmark && (
        <div className="mb-4">
          <BenchmarkTable b={model.data.benchmark} />
        </div>
      )}

      {model.isError ? (
        <ErrorState
          title="The model's measurements could not be loaded"
          detail={model.error instanceof ApiError ? model.error.detail : 'Try again.'}
          onRetry={() => void model.refetch()}
        />
      ) : !m ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton width="100%" height={84} />
          <Skeleton width="60%" />
        </div>
      ) : m.status !== 'measured' ? (
        <EmptyState title={`Not yet measured on ${about.name}`}>
          No measurement of the model on this chain is on file, so no figure is shown. Run <code className="font-mono text-fg">make model MODEL_CHAIN={chain}</code> to train and
          measure it.
          {m.notes.length > 0 && ` ${m.notes.join(' ')}`}
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          <Ledger label="Measured on the test addresses" entries={headline(m)} perRow={3} />

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Panel title="Calibration" note="When the model says 0.9, are nine in ten such addresses deposit addresses? Points on the dashed line mean yes.">
              {m.reliability.length > 0 ? <ReliabilityPlot bins={m.reliability} /> : <p className="text-base text-muted">Not yet measured.</p>}
            </Panel>
            <Panel title="Accuracy when answering, against coverage" note="Answer only the addresses the model is surest about: how many can it answer, and how often is it right?">
              {m.risk_coverage.length > 1 ? (
                <CoveragePlot
                  points={m.risk_coverage}
                  caption="Accuracy on the answered addresses against the share of addresses answered"
                  xTitle="Share of addresses answered (surest first)"
                  yTitle="Right when answering"
                  reference={
                    m.baseline?.accuracy != null
                      ? {
                          value: m.baseline.accuracy,
                          name: 'the one rule alone, answering all',
                        }
                      : undefined
                  }
                />
              ) : (
                <p className="text-base text-muted">Not yet measured.</p>
              )}
            </Panel>
          </div>

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Panel title="What the model reads" note="Share of the model's total gain from each behaviour. It reads no label and no address list.">
              <BarList
                caption="Feature importance"
                labelWidth="16rem"
                rows={m.feature_importance.map((f) => ({
                  key: f.feature,
                  label: f.feature,
                  value: f.importance,
                  valueText: `${(f.importance * 100).toFixed(1)}%`,
                }))}
                empty="Not yet measured."
              />
            </Panel>
            {(m.baseline || m.look_alikes) && (
              <Panel title="Read these against one rule, not against chance">
                {m.baseline && (
                  <p className="max-w-prose text-base text-fg">
                    The single rule <code className="font-mono">{m.baseline.rule}</code> (an address forwards 90% or more of what it receives) scores precision{' '}
                    <span className={mono}>{score(m.baseline.precision)}</span> and recall <span className={mono}>{score(m.baseline.recall)}</span> on the same test addresses. That
                    is the bar the model has to clear.
                  </p>
                )}
                {m.look_alikes && (
                  <p className="max-w-prose text-base text-fg">
                    Its gain is on the look-alikes: of the <span className={mono}>{count(m.look_alikes.negatives)}</span> test wallets that forward as much but are not deposit
                    addresses, the model calls <span className={mono}>{count(m.look_alikes.flagged)}</span> a deposit address (
                    <span className={mono}>{pct(m.look_alikes.false_positive_rate)}</span>
                    ). The rule calls every one of them one.
                  </p>
                )}
              </Panel>
            )}
          </div>

          <Panel
            title="On an exchange it never saw"
            note="Each row is a model trained with that exchange left out entirely, then tested on it. This is what to expect on an exchange no label covers."
          >
            <DataTable caption="Leave one exchange out" columns={foldColumns} rows={m.leave_one_exchange_out} rowKey={(f) => f.exchange} empty="Not yet measured." />
          </Panel>

          {m.abstain ? (
            <Abstain a={m.abstain} />
          ) : (
            <Panel title="The naming bar">
              <p className="text-base text-muted">Not yet measured on {about.name}: the 0.60 naming bar was checked on Tron wallets only.</p>
            </Panel>
          )}

          {m.notes.length > 0 && (
            <Panel title="What these numbers are, and are not">
              <Sentences items={m.notes} />
              <p className="border-t border-rule pt-2 text-sm text-muted">
                Only the model's probability is calibrated. A case's confidence also carries rule-set weights (label tier, hops, share of the funds); see a case's{' '}
                <Link to="/cases" className="underline decoration-rule-strong underline-offset-2 hover:text-fg">
                  evidence
                </Link>{' '}
                for how each was worked out.
              </p>
            </Panel>
          )}
        </div>
      )}

      <div className="mt-4">
        <Throughput />
      </div>
    </>
  )
}
