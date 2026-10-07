import { useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { CaseSummary, Chain } from '../api/models'
import { useCases, useDashboard, useModel } from '../api/queries'
import { ChainBadge } from '../components/ChainBadge'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { Bar, Counter, drawOnMount, layerColor, layerWash } from '../components/Panel'
import { TIERS } from '../components/TierTag'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatPercent, truncateMiddle } from '../lib/format'
import { GlobalSearch } from '../shell/GlobalSearch'
import { StageTrack } from '../shell/StageTrack'
import { DETAIL, PLAIN, STAGE_LAYER, STAGES } from '../stages'
import { featuredCases } from './featured'

const NOT_MEASURED = 'not yet measured'
const NOT_READ = 'could not be read'
const TRACEABLE = (Object.values(CHAINS) as { name: string; traceable?: boolean }[]).filter((c) => c.traceable).map((c) => c.name)
const TIER_ORDER = ['published_por', 'curated', 'explorer_tag', 'derived'] as const

/** What the instrument does, drawn in its own line language: a wallet, hops in the chain
 *  colour, a labelled wallet ringed in the label colour, and the plate the path ends in.
 *  One branch ends in nothing, because that is an answer too. No figure appears in it. */
function TraceSchematic() {
  const hop = (x: number, y: number, name: string) => (
    <g>
      <rect x={x - 46} y={y - 15} width={92} height={30} fill="var(--surface)" stroke="var(--chain)" />
      <text x={x} y={y + 4} textAnchor="middle" fontSize={11} fill="var(--chain)" style={{ fontFamily: '"Public Sans", sans-serif', fontWeight: 600, letterSpacing: '.06em', textTransform: 'uppercase' }}>
        {name}
      </text>
    </g>
  )
  return (
    <svg viewBox="0 0 560 340" className="h-auto w-full max-w-[560px]" aria-hidden="true" focusable="false">
      <path ref={drawOnMount(200)} d="M 96 90 H 190" fill="none" stroke="var(--chain)" />
      <path ref={drawOnMount(450)} d="M 282 90 H 356" fill="none" stroke="var(--chain)" />
      <path ref={drawOnMount(700)} d="M 452 90 H 490 V 150" fill="none" stroke="var(--fusion)" />
      <path ref={drawOnMount(450)} d="M 236 105 V 236 H 300" fill="none" stroke="var(--chain)" />
      <path d="M 392 236 H 470" fill="none" stroke="var(--data)" strokeDasharray="4 4" />

      <rect x={8} y={75} width={88} height={30} fill="var(--chain)" />
      <text x={52} y={94} textAnchor="middle" fontSize={11} fill="var(--surface)" style={{ fontFamily: '"Public Sans", sans-serif', fontWeight: 600, letterSpacing: '.06em' }}>
        SUSPECT
      </text>
      {hop(236, 90, 'hop 1')}
      {hop(402, 90, 'hop 2')}
      {hop(346, 236, 'hop 2')}

      {/* the labelled wallet: ringed in the label colour */}
      <rect x={352} y={71} width={100} height={38} fill="none" stroke="var(--network)" strokeDasharray="2 3" />
      <text x={402} y={62} textAnchor="middle" fontSize={10} fill="var(--network)" style={{ fontFamily: '"Public Sans", sans-serif', fontWeight: 500, letterSpacing: '.06em' }}>
        LABELLED
      </text>

      <g className="anim-rise" style={{ animationDelay: '1100ms' }}>
        <rect x={398} y={150} width={154} height={48} fill="var(--fusion)" />
        <text x={410} y={168} fontSize={10} fill="var(--surface)" style={{ fontFamily: '"Public Sans", sans-serif', fontWeight: 600, letterSpacing: '.075em' }}>
          ATTRIBUTED
        </text>
        <text x={410} y={188} fontSize={15} fill="var(--surface)" style={{ fontFamily: 'Archivo, sans-serif', fontWeight: 700 }}>
          Exchange named
        </text>
      </g>
      <g className="anim-rise" style={{ animationDelay: '1300ms' }}>
        <rect x={390.5} y={258.5} width={161} height={48} fill="var(--surface)" stroke="var(--data)" strokeDasharray="4 4" />
        <text x={402} y={276} fontSize={10} fill="var(--ink-soft)" style={{ fontFamily: '"Public Sans", sans-serif', fontWeight: 600, letterSpacing: '.075em' }}>
          INSUFFICIENT EVIDENCE
        </text>
        <text x={402} y={296} fontSize={15} fill="var(--ink)" style={{ fontFamily: 'Archivo, sans-serif', fontWeight: 700 }}>
          No exchange named
        </text>
      </g>
      <path d="M 470 236 V 258" fill="none" stroke="var(--data)" strokeDasharray="4 4" />
    </svg>
  )
}

function CaseTile({ c }: { c: CaseSummary }) {
  return (
    <Link
      to={`/cases/${encodeURIComponent(c.id)}`}
      className="flex h-full flex-col gap-1.5 border border-rule bg-surface px-3 py-2 transition-colors duration-150 hover:border-ink"
    >
      <span className="flex items-center gap-2">
        <span className="truncate font-cond text-sm font-bold tracking-tight text-ink">{c.case_ref ?? c.id}</span>
        <ChainBadge chain={c.chain} size="sm" />
        <span className="ml-auto truncate font-mono text-2xs text-ink-dim">{truncateMiddle(c.address, 4, 4)}</span>
      </span>
      <OutcomeStamp outcome={c.outcome ?? null} status={c.status} vasp={c.top_vasp} className="self-start" />
    </Link>
  )
}

/** How often naming is right, beside the recorded wallets. Read from the measurement; with
 *  no measurement the line is not drawn (the figures below the fold say "not yet measured"). */
function NamingRecord() {
  const model = useModel('tron').data
  const a = model?.abstain
  const bar = a?.bars.find((b) => b.threshold === a.current_threshold)
  if (!a || !bar) return null
  const others = (model?.benchmark?.chains ?? []).filter((r) => r.measured && r.chain !== a.chain && (r.wallets ?? 0) > 0)
  const measuredOn = CHAINS[a.chain as Chain]?.name ?? a.chain
  const n = (v: number) => <span className="font-mono text-ink">{v.toLocaleString('en-US')}</span>
  return (
    <p className="mt-3 border-l-2 border-fusion pl-3 text-sm text-ink-soft" data-testid="naming-record">
      Measured on {n(a.wallets)} real exchange customers’ wallets on {measuredOn}: {n(bar.wallets_named)} named, {n(bar.wallets_wrong)} of those wrongly.
      The rest got “insufficient evidence”.{' '}
      {others.length > 0 ? (
        <span data-testid="naming-record-others">
          Measured on fewer wallets elsewhere:{' '}
          {others
            .map((r) => `${CHAINS[r.chain as Chain]?.name ?? r.chain} ${r.wallets} (${r.named} named, ${r.wrong} wrongly)`)
            .join('; ')}
          . Each answer quotes the figure of its own chain.
        </span>
      ) : (
        'On every other chain an answer rests on labels and tracing rules, and that error rate does not cover it.'
      )}
    </p>
  )
}

/** The recorded wallets: real, already traced, one click from a case. Grouped by what the
 *  tool said about each, because declining to name an exchange is an answer too. */
function RecordedCases() {
  const cases = useCases()
  const all = cases.data?.items ?? []
  const { named, notNamed } = featuredCases(all)
  if (cases.isPending) return <p className="colhead">Looking for recorded wallets…</p>
  if (named.length + notNamed.length === 0) {
    const shown = all.slice(0, 4)
    if (shown.length === 0) return null
    return (
      <div>
        <p className="colhead mb-2">or open a case on file</p>
        <ul aria-label="Cases on file" className="grid gap-2 sm:grid-cols-2">
          {shown.map((c) => (
            <li key={c.id}><CaseTile c={c} /></li>
          ))}
        </ul>
      </div>
    )
  }
  const group = (heading: string, list: CaseSummary[]) =>
    list.length > 0 && (
      <div>
        <h2 className="colhead mb-1.5 text-ink-soft">{heading}</h2>
        <ul aria-label={heading} className="grid gap-2 sm:grid-cols-2">
          {list.map((c) => (
            <li key={c.id}><CaseTile c={c} /></li>
          ))}
        </ul>
      </div>
    )
  return (
    <section aria-label="Recorded wallets">
      <p className="colhead mb-2">or open a recorded wallet: real, already traced</p>
      <div className="flex flex-col gap-3">
        {group('Named an exchange', named)}
        {group('Did not name one, and says why', notNamed)}
      </div>
      <NamingRecord />
    </section>
  )
}

/** One measured figure beside what it was measured on. A figure with no source says so. */
function Measured({ label, value, children, layer = 'fusion' }: { label: string; value: ReactNode; children: ReactNode; layer?: 'fusion' | 'network' | 'chain' | 'confirm' }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 border-l-2 pl-3" style={{ borderColor: layerColor(layer) }}>
      <p className="colhead">{label}</p>
      <p className={cx(value === NOT_MEASURED || value === NOT_READ ? 'title text-lg text-ink-soft' : 'figure text-ink')}>{value}</p>
      <div className="text-sm text-ink-soft">{children}</div>
    </div>
  )
}

/** The mechanism, below the fold: the nine stages, then what was measured. Every figure is
 *  read from the tool's own measurements when the page opens; none is typed here. */
function HowItWorks() {
  const [at, setAt] = useState(3)
  const dashboard = useDashboard()
  const model = useModel('tron')

  const cover = dashboard.data?.label_coverage
  const tiers = cover ? TIER_ORDER.map((t) => [t, cover.by_tier[t] ?? 0] as const) : []
  const most = Math.max(1, ...tiers.map(([, n]) => n))
  const m = model.data?.status === 'measured' ? model.data : null
  const a = model.data?.abstain
  const bar = a?.bars.find((b) => b.threshold === a.current_threshold)
  const layer = STAGE_LAYER[at]
  const unread = 'The measurements could not be read just now. Reload the page to try again.'

  return (
    <section id="how" aria-labelledby="how-title" className="relative scroll-mt-12 border-t border-rule">
      <div className="mx-auto flex max-w-content flex-col gap-8 px-3 py-8 sm:px-6">
        {/* Text never sits on the grid: each band is an opaque plate on it. */}
        <div className="bg-paper">
          <p className="eyebrow">How it works</p>
          <h2 id="how-title" className="display mt-1 text-ink">
            Nine stages, from a pasted address to a request letter
          </h2>
          <p className="mt-2 max-w-[82ch] text-md text-ink-soft">
            The same nine stages run for every wallet. A trace shows them lighting up as it goes; here each one says what it does, first in plain words,
            then the mechanism.
          </p>
        </div>

        <div className="panel p-4">
          <div className="hidden lg:block">
            <StageTrack stages={STAGES} idx={at} layer={layer} onPick={setAt} />
          </div>
          <div className="grid gap-6 lg:mt-2 lg:grid-cols-[260px_minmax(0,1fr)] lg:border-t lg:border-rule lg:pt-4">
            <ol aria-label="The nine stages" className="flex flex-col">
              {STAGES.map(([name, what], i) => {
                const on = i === at
                return (
                  <li key={name}>
                    {/* Only the chosen row is coloured: nine coloured rows would put five hues on
                        screen and dilute the key the footer exists to teach. */}
                    <button
                      type="button"
                      aria-pressed={on}
                      onClick={() => setAt(i)}
                      className={cx('flex w-full items-baseline gap-2 border-l-2 px-2 py-1 text-left transition-colors duration-150', !on && 'border-transparent hover:bg-active-wash')}
                      style={on ? { borderColor: layerColor(STAGE_LAYER[i]), background: layerWash(STAGE_LAYER[i]) } : undefined}
                    >
                      <span className="w-4 shrink-0 font-mono text-2xs text-ink-dim">{i + 1}</span>
                      <span className="min-w-0">
                        <span className="block font-cond text-sm font-bold uppercase tracking-tight text-ink">{name}</span>
                        <span className="block text-sm text-ink-soft">{what}</span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ol>
            <div aria-live="polite" className="min-w-0">
             <div key={at} className="anim-rise">
              <p className="colhead" style={{ color: layerColor(layer) }}>
                Stage {at + 1} of {STAGES.length} · {STAGES[at][0]}
              </p>
              <p className="mt-2 max-w-[70ch] text-md text-ink">{PLAIN[at]}</p>
              <h3 className="title mt-4 text-lg text-ink">{DETAIL[at][0]}</h3>
              <p className="mt-1 max-w-[82ch] text-base text-ink-soft">{DETAIL[at][1]}</p>
             </div>
            </div>
          </div>
        </div>

        <div className="bg-paper">
          <p className="eyebrow">Measured, not claimed</p>
          <h2 className="display mt-1 text-ink">What the numbers are</h2>
          <p className="mt-2 max-w-[82ch] text-md text-ink-soft">
            Each figure below is read from this installation’s own measurements as the page opens. Where a measurement does not exist yet, the page says
            so; it never shows a number in its place.
          </p>
        </div>

        <div className="panel grid gap-x-8 gap-y-6 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Measured label="Labelled addresses on chains that trace" layer="network" value={cover ? <Counter value={cover.traceable_total ?? cover.total} /> : dashboard.isPending ? '…' : dashboard.isError ? NOT_READ : NOT_MEASURED}>
            {cover ? (
              <>
              {cover.traceable_total != null && cover.traceable_total < cover.total && (
                <p className="mb-1.5">
                  Of <span className="font-mono text-ink">{cover.total.toLocaleString('en-US')}</span> on file: the rest are on chains this tool cannot trace yet. By
                  evidence tier, all chains:
                </p>
              )}
              <ul className="mt-1 flex flex-col gap-1">
                {tiers.map(([tier, n], i) => (
                  <li key={tier} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2">
                    <span className="truncate">{TIERS[tier].name}</span>
                    <span className="font-mono text-ink">{n.toLocaleString('en-US')}</span>
                    <span className="col-span-2">
                      <Bar value={n} max={most} layer="network" width="100%" height={4} delay={i * 80} />
                    </span>
                  </li>
                ))}
              </ul>
              </>
            ) : (
              dashboard.isError ? 'The label counts could not be read just now. Reload the page to try again.' : 'Counting…'
            )}
          </Measured>

          <Measured label="Named wrongly at the bar in use" value={bar && bar.wallets_named > 0 ? formatPercent(bar.wallets_wrong / bar.wallets_named) : model.isPending ? '…' : model.isError ? NOT_READ : NOT_MEASURED}>
            {a && bar ? (
              <>
                Of <span className="font-mono text-ink">{a.wallets.toLocaleString('en-US')}</span> real exchange customers’ wallets on{' '}
                {CHAINS[a.chain as Chain]?.name ?? a.chain} traced with the derived
                labels hidden, <span className="font-mono text-ink">{bar.wallets_named.toLocaleString('en-US')}</span> were named at the{' '}
                <span className="font-mono text-ink">{a.current_threshold.toFixed(2)}</span> bar and{' '}
                <span className="font-mono text-ink">{bar.wallets_wrong.toLocaleString('en-US')}</span> of those wrongly
                {bar.risk_upper_bound != null && (
                  <>
                    {' '}
                    (upper bound <span className="font-mono text-ink">{formatPercent(bar.risk_upper_bound)}</span>)
                  </>
                )}
                . Other chains were not in this measurement. A named exchange is a lead to confirm, not proof.
              </>
            ) : (
              model.isError ? unread : 'The naming bar has not been measured on this installation.'
            )}
          </Measured>

          <Measured label="Calibration error of the deposit-address model" value={m?.metrics.ece != null ? m.metrics.ece.toFixed(4) : model.isPending ? '…' : model.isError ? NOT_READ : NOT_MEASURED}>
            {m ? (
              <>
                Expected calibration error on Tron
                {m.metrics.n_test != null && (
                  <>
                    , on <span className="font-mono text-ink">{m.metrics.n_test.toLocaleString('en-US')}</span> held-out wallets
                  </>
                )}
                . Split {m.split}. Zero would mean a stated probability is exactly the observed rate.
              </>
            ) : (
              model.isError ? unread : 'The deposit-address model has not been measured on this installation.'
            )}
          </Measured>

          <Measured label="Wallets the model gives an answer for" value={m?.metrics.coverage != null ? formatPercent(m.metrics.coverage) : model.isPending ? '…' : model.isError ? NOT_READ : NOT_MEASURED}>
            {m ? (
              <>
                It declines the rest.
                {m.metrics.accuracy_when_answering != null && (
                  <>
                    {' '}
                    When it answers, it was right <span className="font-mono text-ink">{formatPercent(m.metrics.accuracy_when_answering)}</span> of the time on
                    the held-out wallets.
                  </>
                )}{' '}
                <Link to="/model" className="font-medium text-ink underline decoration-rule-strong underline-offset-2 hover:decoration-ink">
                  How each figure was measured
                </Link>
              </>
            ) : (
              <Link to="/model" className="font-medium text-ink underline decoration-rule-strong underline-offset-2 hover:decoration-ink">
                The Model page says what exists
              </Link>
            )}
          </Measured>
        </div>
      </div>
    </section>
  )
}

/** The landing: the instrument at rest, waiting for a wallet.
 *
 *  Two screens stacked. A one-viewport hero (the argument and the paste box on the left, the
 *  trace drawn on the right), then the mechanism below the fold. The page scrolls, which is
 *  also what gives the header its ground. Not a centred hero over a gradient: a forensics
 *  tool should read as apparatus. */
export function StartPage() {
  const hasRecorded = (useCases().data?.items ?? []).some((c) => c.demo)
  // The grid is the ground for the whole landing; it is fixed, so it stays put under the scroll.
  return (
    <div className="relative flex flex-1 flex-col">
      <div aria-hidden className="plate-grid pointer-events-none fixed inset-0 -z-0" />

      {/* 5rem: the header above plus the status bar below. */}
      <section aria-labelledby="start-title" className="relative flex min-h-[calc(100svh-5rem)] flex-col">
        {/* A veil, not a card: solid paper under the column that holds the text, thinning to
            nothing across the grid, so contrast is carried by the page. It starts where the
            grid does, under the header, or a seam shows at the header's edge. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -top-12 bottom-0 left-0 right-0"
          style={{
            background:
              'linear-gradient(to right, var(--paper) 0%, var(--paper) 48%, color-mix(in srgb, var(--paper) 70%, transparent) 62%, color-mix(in srgb, var(--paper) 20%, transparent) 82%, transparent 100%)',
          }}
        />

        <div className="relative mx-auto grid w-full max-w-content flex-1 items-center gap-8 px-3 py-8 sm:px-6 lg:grid-cols-[minmax(0,46rem)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col gap-6">
            <div>
              <h1 id="start-title" className="display anim-rise text-ink" style={{ fontSize: 'clamp(32px,5vw,60px)' }}>
                Wallet <span className="text-chain">→</span> exchange
                <br />
                attribution
              </h1>
              <p className="anim-rise mt-4 max-w-[58ch] text-md text-ink-soft" style={{ animationDelay: '80ms' }}>
                A stolen-funds complaint gives you a wallet address and nothing else. This follows that wallet’s money{' '}
                <span className="font-semibold text-chain">on chain</span> to the nearest exchange that took it, names the exchange only when the{' '}
                <span className="font-semibold text-network">label evidence</span> holds, drafts the request to send it, and says{' '}
                <em>insufficient evidence</em> when it cannot be sure.
              </p>
            </div>

            <div className="anim-rise" style={{ animationDelay: '160ms' }}>
              <GlobalSearch variant="hero" />
              <p className="mt-2 text-sm text-ink-soft">
                {TRACEABLE.slice(0, -1).join(', ')} and {TRACEABLE.at(-1)}. The chain is read from the address.{' '}
                <Link to="/cases/new" className="font-medium text-ink underline decoration-rule-strong underline-offset-2 hover:decoration-ink">
                  Open a case with its complaint details
                </Link>
              </p>
            </div>

            <div className="anim-rise" style={{ animationDelay: '240ms' }}>
              <RecordedCases />
            </div>

            <p className="anim-rise flex flex-wrap items-center gap-x-6 gap-y-2 text-2xs text-ink-dim" style={{ animationDelay: '320ms' }}>
              {hasRecorded && (
                <span className="flex items-center gap-2">
                  <span aria-hidden className="inline-block h-1.5 w-1.5 bg-confirm" />
                  recorded wallets replay with the network closed
                </span>
              )}
              <Link to="/cases" className="text-chain hover:underline">
                all cases
              </Link>
              <Link to="/coverage" className="text-chain hover:underline">
                problem statement, line by line
              </Link>
            </p>
          </div>

          <div className="relative hidden justify-end lg:flex"><TraceSchematic /></div>
        </div>

        <a href="#how" className="colhead anim-rise relative mx-auto mb-4 transition-colors duration-150 hover:text-ink" style={{ animationDelay: '520ms' }}>
          how it works ↓
        </a>
      </section>

      <div className="relative">
        <HowItWorks />
      </div>
    </div>
  )
}
