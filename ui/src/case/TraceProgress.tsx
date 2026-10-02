import { useEffect, useState } from 'react'
import type { CaseDetail } from '../api/models'
import { Button } from '../components/Button'
import { CHAINS } from '../lib/chains'
import { formatDuration } from '../lib/format'

function Fact({ name, value }: { name: string; value: number }) {
  return (
    <div className="flex flex-col">
      <dt className="eyebrow">{name}</dt>
      <dd className="tabular font-mono text-lg font-medium text-fg">{value.toLocaleString('en-US')}</dd>
    </div>
  )
}

/** A trace that is still running. It shows what the server says the trace has read so far
 *  (`CaseDetail.progress`: its sentence as it came, and the counts behind it), and how long
 *  the officer has been waiting. There is no percentage: a trace does not know how much is
 *  left. The server has no way to cancel a trace, so "Stop waiting" leaves; the trace goes
 *  on and the case stays in the list. */
export function TraceProgress({ c, onStop }: { c: CaseDetail; onStop: () => void }) {
  const [waited, setWaited] = useState(0)
  useEffect(() => {
    const began = Date.now()
    const timer = window.setInterval(() => setWaited(Math.round((Date.now() - began) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const p = c.progress
  const sentence = p
    ? p.message
    : c.status === 'queued'
      ? 'Waiting to start.'
      : `Reading the wallet’s transfers on ${CHAINS[c.chain].name} and following the money, hop by hop.`

  return (
    <section aria-labelledby="trace-title" className="mt-4 flex max-w-[720px] flex-col gap-3 rounded-md border border-dashed border-rule-strong px-5 py-4">
      <h2 id="trace-title" className="text-base font-semibold text-fg">
        Tracing the wallet
      </h2>
      <p role="status" className="text-base text-fg [overflow-wrap:anywhere]">
        {sentence}
      </p>
      {p && p.phase !== 'reading' && (
        <dl role="group" aria-label="Read so far" className="flex flex-wrap gap-x-8 gap-y-2">
          <Fact name="Hops out" value={p.hop} />
          <Fact name="Wallets read" value={p.wallets_read} />
          <Fact name="Transfers read" value={p.transfers_read} />
        </dl>
      )}
      <p className="text-sm text-muted">
        Each branch ends at the first labelled wallet, at a busy wallet where funds from many senders mix, or at the hop limit. A labelled wallet reached
        is not yet the answer: which exchange is named, if any, is decided when the trace is done.
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button onClick={onStop}>Stop waiting</Button>
        <span className="tabular font-mono text-xs text-muted">{waited > 0 ? `Waited ${formatDuration(waited)}` : 'Just started'}</span>
        <span className="text-xs text-muted">The trace keeps running on the server; the case stays in the list.</span>
      </div>
    </section>
  )
}
