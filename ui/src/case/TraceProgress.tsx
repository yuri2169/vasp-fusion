import { useEffect, useState } from 'react'
import type { CaseDetail } from '../api/models'
import { Button } from '../components/Button'
import { Panel } from '../components/Panel'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatDuration } from '../lib/format'
import { StageTrack } from '../shell/StageTrack'
import { DETAIL, STAGES, stageOf } from '../stages'

function Fact({ name, value }: { name: string; value: number }) {
  return (
    <div className="flex flex-col">
      <dt className="colhead">{name}</dt>
      <dd className="tabular font-mono text-md font-semibold text-chain">{value.toLocaleString('en-US')}</dd>
    </div>
  )
}

/** A trace that is still running: the nine stages, lit as far as the trace has got.
 *
 *  Everything here is what the trace itself reports (`CaseDetail.progress`: its sentence as it
 *  came, its phase, and the counts behind it), and how long the officer has been waiting.
 *  There is no percentage: a trace does not know how much is left. It reports four phases, so
 *  the track lights the stage each belongs to. The wait is the longest uninterrupted attention
 *  this screen gets, so it explains the stage that is running. There is no way to cancel a
 *  trace, so "Stop waiting" leaves; the trace goes on and the case stays in the list. */
export function TraceProgress({ c, onStop }: { c: CaseDetail; onStop: () => void }) {
  const [waited, setWaited] = useState(0)
  useEffect(() => {
    const began = Date.now()
    const timer = window.setInterval(() => setWaited(Math.round((Date.now() - began) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const p = c.progress
  const idx = stageOf(c.status, p?.phase)
  const sentence = p
    ? p.message
    : c.status === 'queued'
      ? 'Waiting to start.'
      : `Reading the wallet’s transfers on ${CHAINS[c.chain].name} and following the money, hop by hop.`

  return (
    <Panel aria-labelledby="trace-title" className="mt-4 flex flex-col gap-4">
      <div className="flex flex-wrap items-start gap-x-8 gap-y-3">
        <div className="min-w-0 flex-1 basis-[420px]">
          <h2 id="trace-title" className="title text-lg text-ink">
            Tracing the wallet
          </h2>
          <p role="status" className="mt-1 max-w-[82ch] text-base text-ink [overflow-wrap:anywhere]">
            {sentence}
          </p>
        </div>
        <div className="flex shrink-0 items-end gap-6">
          <div>
            <span className="figure text-ink" style={{ fontSize: 30 }}>
              {idx + 1}
            </span>
            <span className="font-mono text-sm text-ink-soft">/{STAGES.length}</span>
            <span className="colhead mt-0.5 block">stage</span>
          </div>
          {p && p.phase !== 'reading' && (
            <dl role="group" aria-label="Read so far" className="flex gap-x-6">
              <Fact name="Hops out" value={p.hop} />
              <Fact name="Wallets read" value={p.wallets_read} />
              <Fact name="Transfers read" value={p.transfers_read} />
            </dl>
          )}
        </div>
      </div>

      <div className="hidden lg:block">
        <StageTrack stages={STAGES} idx={idx} live notes={{ [STAGES[idx][0]]: 'running' }} />
      </div>
      <ol aria-label="Stages of the trace" className="grid gap-x-6 gap-y-1 sm:grid-cols-3 lg:sr-only">
        {STAGES.map(([name, what], i) => (
          <li key={name} aria-current={i === idx ? 'step' : undefined} className="flex items-baseline gap-2">
            <span aria-hidden className={cx('mt-1 h-2 w-2 shrink-0', i <= idx ? 'bg-chain' : 'bg-rule', i === idx && 'blink')} />
            <span className="min-w-0">
              <span className={cx('font-cond text-sm font-bold uppercase tracking-tight', i <= idx ? 'text-ink' : 'text-ink-dim')}>{name}</span>
              <span className="sr-only">
                : {what}. {i < idx ? 'Done.' : i === idx ? 'Running.' : 'Not started.'}
              </span>
            </span>
          </li>
        ))}
      </ol>

      <div className="grid gap-6 border-t border-rule pt-4 md:grid-cols-[minmax(0,1fr)_auto]">
        <div key={idx} className="anim-rise min-w-0">
          <p className="colhead mb-1 text-chain">Now running</p>
          <h3 className="title text-lg text-ink">{DETAIL[idx][0]}</h3>
          <p className="mt-1 max-w-[82ch] text-base text-ink-soft">{DETAIL[idx][1]}</p>
          <p className="mt-2 max-w-[82ch] text-sm text-ink-soft">
            Each branch ends at the first labelled wallet, at a busy wallet where funds from many senders mix, or at the hop limit. A labelled wallet reached
            is not yet the answer: which exchange is named, if any, is decided when the trace is done.
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-start gap-2 md:border-l md:border-rule md:pl-6">
          <span className="colhead">Waited</span>
          <span className="tabular font-mono text-md font-semibold text-ink">{waited > 0 ? formatDuration(waited) : 'Just started'}</span>
          <Button onClick={onStop}>Stop waiting</Button>
          <span className="max-w-[26ch] text-sm text-ink-soft">The trace keeps running if you leave; the case stays in the list.</span>
        </div>
      </div>
    </Panel>
  )
}
