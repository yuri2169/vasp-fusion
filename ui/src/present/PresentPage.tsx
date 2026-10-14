import { lazy, Suspense, useCallback, useEffect, useRef, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import type { CaseDetail } from '../api/models'
import { useCase } from '../api/queries'
import { ROUTE_WORDS } from '../case/WriteOrderPanel'
import { NAMING_BAR } from '../case/rules'
import { DualMeter } from '../components/DualMeter'
import { FundsBar } from '../components/FundsBar'
import { HopRail } from '../components/HopRail'
import { Skeleton } from '../components/Skeleton'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatAmount, formatPercent, truncateMiddle } from '../lib/format'
import { count } from '../overview/words'

const FlowGraph = lazy(() => import('../case/FlowGraph').then((m) => ({ default: m.FlowGraph })))

/** The four screens, in the order a case is told. */
export const SCREENS = ['The finding', 'The route', 'What was left out, and why', 'The handoff'] as const

/** Full-screen, keyboard-driven: one case for a projector, in four screens. It reads the same case the case page
 *  reads and adds nothing to it. ← → move between screens, 1 to 4 jump, F fills the screen, Esc goes back. */
export function PresentPage() {
  const { id = '' } = useParams()
  const q = useCase(id)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const at = Math.min(SCREENS.length - 1, Math.max(0, Number(params.get('screen') ?? 1) - 1 || 0))
  const root = useRef<HTMLDivElement>(null)

  const go = useCallback(
    (n: number) => {
      const next = Math.min(SCREENS.length - 1, Math.max(0, n))
      setParams(next === 0 ? {} : { screen: String(next + 1) }, { replace: true })
    },
    [setParams],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const tag = (e.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') go(at + 1)
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') go(at - 1)
      else if (e.key === 'Home') go(0)
      else if (e.key === 'End') go(SCREENS.length - 1)
      else if (/^[1-4]$/.test(e.key)) go(Number(e.key) - 1)
      else if (e.key === 'f' || e.key === 'F') {
        if (document.fullscreenElement) void document.exitFullscreen?.()
        else void root.current?.requestFullscreen?.().catch(() => undefined)
      } else if (e.key === 'Escape') {
        if (document.fullscreenElement) return // the browser leaves full screen first
        navigate(`/cases/${encodeURIComponent(id)}`)
      } else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [at, go, id, navigate])

  useEffect(() => {
    root.current?.focus()
  }, [])

  const c = q.data
  const ready = c && c.status === 'done' && c.outcome
  return (
    <div ref={root} tabIndex={-1} data-present className="flex h-screen flex-col overflow-hidden bg-paper text-ink outline-none">
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-rule px-8 py-4">
        <p className="flex flex-wrap items-baseline gap-x-4">
          <span className="eyebrow !text-lg">Case {c?.case_ref ?? id}</span>
          {c && (
            <span className="font-mono text-2xl text-chain">
              {CHAINS[c.chain]?.code} {truncateMiddle(c.address, 8, 8)}
            </span>
          )}
        </p>
        <p className="text-lg text-ink-soft">
          <kbd className="font-mono">←</kbd> <kbd className="font-mono">→</kbd> move · <kbd className="font-mono">F</kbd> full screen ·{' '}
          <Link to={`/cases/${encodeURIComponent(id)}`} className="underline underline-offset-2">
            Esc leaves
          </Link>
        </p>
      </header>

      <p className="sr-only" aria-live="polite">
        Screen {at + 1} of {SCREENS.length}: {SCREENS[at]}
      </p>

      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto px-8 py-6">
        {q.isError && <Big>This case could not be opened.</Big>}
        {!q.isError && !c && <Skeleton width="40%" />}
        {c && !ready && <Big>This case has no finished trace to present yet.</Big>}
        {ready && (
          <section key={at} aria-labelledby="present-title" className="anim-rise flex min-h-0 flex-1 flex-col gap-6">
            <h1 id="present-title" className="eyebrow !text-lg">
              {at + 1} · {SCREENS[at]}
            </h1>
            {at === 0 && <Finding c={c} />}
            {at === 1 && <Route c={c} />}
            {at === 2 && <LeftOut c={c} />}
            {at === 3 && <Handoff c={c} />}
          </section>
        )}
      </main>

      <nav aria-label="Screens" className="border-t border-rule px-8 py-4">
        <ol className="flex items-center">
          {SCREENS.map((name, i) => (
            <li key={name} className={cx('flex items-center', i < SCREENS.length - 1 && 'flex-1')}>
              <button
                type="button"
                onClick={() => go(i)}
                aria-current={i === at ? 'step' : undefined}
                className={cx('flex items-center gap-2.5 whitespace-nowrap py-1 text-lg', i === at ? 'font-semibold text-ink' : 'text-ink-soft hover:text-ink')}
              >
                <span aria-hidden className={cx('inline-block size-4 border-2 border-chain', i <= at ? 'bg-chain' : 'bg-surface')} />
                {name}
              </button>
              {i < SCREENS.length - 1 && <span aria-hidden className={cx('mx-3 h-0 flex-1 border-t-2', i < at ? 'border-chain' : 'border-dashed border-rule-strong')} />}
            </li>
          ))}
        </ol>
      </nav>
    </div>
  )
}

function Big({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cx('max-w-[44ch] text-[clamp(22px,2.4vw,34px)] leading-snug text-ink', className)}>{children}</p>
}

/** 1. What the case came to: the exchange, proximity and confidence apart; or why none is named. */
function Finding({ c }: { c: CaseDetail }) {
  const top = c.candidates.find((k) => k.vasp === c.top_vasp && k.direction === 'outbound') ?? c.candidates.find((k) => k.vasp === c.top_vasp)
  if (c.outcome === 'INSUFFICIENT_EVIDENCE')
    return (
      <div className="flex flex-col gap-6">
        <p className="display !text-[clamp(44px,6.5vw,104px)] leading-none text-data">No exchange is named</p>
        <Big>{c.abstain_reason}</Big>
        {(c.what_would_change?.length ?? 0) > 0 && (
          <div>
            <p className="colhead !text-sm">What would change this</p>
            <ul className="mt-3 flex flex-col gap-3">
              {c.what_would_change.slice(0, 3).map((w) => (
                <li key={w} className="max-w-[80ch] border-l-4 border-data pl-4 text-2xl text-ink">
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    )
  const alerts = c.typology_flags.filter((f) => f.severity === 'high')
  return (
    <div className="flex flex-col gap-8">
      {c.outcome === 'SANCTIONED_OR_MIXER_REACHED' ? (
        <>
          <p className="display !text-[clamp(40px,5.6vw,92px)] leading-none text-danger">Sanctioned address or mixer reached</p>
          <ul className="flex flex-col gap-2">
            {alerts.slice(0, 3).map((f) => (
              <li key={f.text} className="max-w-[70ch] border-l-4 border-danger pl-4 text-2xl text-ink">
                {f.text}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <div>
          <p className="colhead !text-sm">The traced money reached</p>
          <p className="display !text-[clamp(56px,9vw,152px)] normal-case leading-none text-fusion">{c.top_vasp}</p>
        </div>
      )}
      {top && (
        <div className="max-w-[1100px] [zoom:1.5]">
          <DualMeter
            proximityRank={top.proximity_rank}
            hops={top.hops}
            shareOfFunds={top.share_of_funds}
            timeToReachS={top.time_to_reach_s}
            confidence={top.confidence}
            interval={top.confidence_interval}
            bar={NAMING_BAR}
          />
        </div>
      )}
      {c.outcome === 'ATTRIBUTED' && <Big className="text-ink-soft">A lead to confirm with the exchange, not proof of who holds the account.</Big>}
    </div>
  )
}

/** 2. How the money went: the Hop Rail, then the graph with its replay. */
function Route({ c }: { c: CaseDetail }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="[zoom:1.25]">
        <HopRail
          suspect={{ address: c.address, chain: c.chain }}
          hops={c.hop_rail}
          stamp={{ outcome: c.outcome ?? null, status: 'done', vasp: c.top_vasp, confidence: c.confidence, whatWouldChange: c.what_would_change?.[0] }}
        />
      </div>
      <Suspense fallback={<Skeleton width="30%" />}>
        <FlowGraph c={c} selected={null} onSelect={() => undefined} className="min-h-0 flex-1" />
      </Suspense>
    </div>
  )
}

/** 3. What the trace did not follow, and why, in its own counts. */
export function LeftOut({ c }: { c: CaseDetail }) {
  const s = c.trace_summary
  return (
    <div className="flex flex-col gap-8">
      {s && (
        <p className="display !text-[clamp(36px,5vw,80px)] normal-case leading-tight">
          Followed {count(s.transfers_followed)} of {count(s.transfers_seen)} transfers seen
        </p>
      )}
      {s && s.not_followed.length > 0 && (
        <ul className="grid max-w-[1200px] gap-x-10 gap-y-3 sm:grid-cols-2">
          {s.not_followed.map((r) => (
            <li key={r.reason} className="border-l-4 border-data pl-4 text-2xl text-ink">
              {r.text}
            </li>
          ))}
        </ul>
      )}
      {s && s.not_followed.length === 0 && <Big>Every wallet the money reached was read.</Big>}
      {!s && <Big>This result was stored without the trace’s counts. Trace it again to see what was followed.</Big>}
      {(c.where_funds_went?.length ?? 0) > 0 && (
        <div className="max-w-[1400px] [zoom:1.3]">
          <FundsBar slices={c.where_funds_went} asset={c.asset ?? ''} total={c.total_sent} named={c.outcome === 'ATTRIBUTED' ? c.top_vasp : null} />
        </div>
      )}
      {c.provenance.budget?.ended_by && <Big className="text-ink-soft">{c.provenance.budget.text}</Big>}
    </div>
  )
}

/** 4. Who is asked, by what route: the exchange request, and the issuer's when one is offered. */
function Handoff({ c }: { c: CaseDetail }) {
  const rows = c.write_order?.exchanges ?? []
  const issuer = c.issuer_request?.offered ? c.issuer_request.draft : null
  return (
    <div className="flex flex-col gap-8">
      {rows.length === 0 && (
        <>
          <p className="display !text-[clamp(36px,5vw,80px)] normal-case leading-tight text-data">No exchange request is offered</p>
          {(c.next_steps?.length ?? 0) > 0 && (
            <ul className="flex flex-col gap-4">
              {c.next_steps.slice(0, 3).map((n) => (
                <li key={n} className="max-w-[80ch] border-l-4 border-data pl-4 text-2xl text-ink">
                  {n}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      {rows.length > 0 && (
        <ol className="flex flex-col gap-6">
          {rows.map((x) => (
            <li key={x.vasp} className="grid max-w-[1300px] gap-x-8 gap-y-1 sm:grid-cols-[auto_minmax(0,1fr)]">
              <span className="display !text-[clamp(32px,4vw,64px)] normal-case leading-none text-fusion">{x.vasp}</span>
              <span className="flex flex-col gap-1 text-2xl text-ink">
                <span>
                  {formatPercent(x.share_of_funds)} of the funds, {formatAmount(x.amount, x.asset ?? '')}
                </span>
                <span className="text-ink-soft">
                  {ROUTE_WORDS[x.route]}
                  {x.request_status ? ` · request ${x.request_status.replace('_', ' ')}` : ' · no request drafted yet'}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
      {issuer && (
        <div className="max-w-[1300px] border-l-4 border-chain pl-5">
          <p className="text-2xl font-semibold text-chain">And a draft to the issuer of USDT</p>
          <p className="mt-1 text-2xl text-ink">
            {issuer.wallets.length} address{issuer.wallets.length === 1 ? '' : 'es'} outside any exchange, holding{' '}
            {formatAmount(
              issuer.wallets.reduce((t, w) => t + w.held, 0),
              'USDT',
            )}{' '}
            of the traced funds. The issuer can freeze USDT at an address; the draft is for the officer, and nothing is sent.
          </p>
        </div>
      )}
    </div>
  )
}
