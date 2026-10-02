import { useEffect, useState } from 'react'
import type { CaseDetail } from '../api/models'
import { Button } from '../components/Button'
import { CHAINS } from '../lib/chains'
import { formatDuration } from '../lib/format'

/** A trace that is still running. It says only what is known: whether the trace has started,
 *  which chain is being read, and how long the officer has been waiting. The server reports
 *  no step-by-step progress and has no way to cancel, so this neither invents steps nor
 *  pretends to stop the trace: "Stop waiting" leaves, and the case stays in the list. */
export function TraceProgress({ c, onStop }: { c: CaseDetail; onStop: () => void }) {
  const [waited, setWaited] = useState(0)
  useEffect(() => {
    const began = Date.now()
    const timer = window.setInterval(() => setWaited(Math.round((Date.now() - began) / 1000)), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const chain = CHAINS[c.chain].name
  return (
    <section aria-labelledby="trace-title" className="mt-4 flex max-w-prose flex-col gap-3 rounded-md border border-dashed border-rule-strong px-5 py-4">
      <h2 id="trace-title" className="text-base font-semibold text-fg">
        Tracing the wallet
      </h2>
      <p role="status" className="text-sm text-fg">
        {c.status === 'queued'
          ? 'Waiting to start.'
          : `Reading the wallet’s transfers on ${chain} and following the money, hop by hop.`}
      </p>
      <p className="text-sm text-muted">
        Each branch ends at the first labelled wallet, at a busy wallet where funds from many senders mix, or at the hop limit. A trace takes 1 to 10
        seconds from the live chain, and less from the cache.
      </p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button onClick={onStop}>Stop waiting</Button>
        <span className="tabular font-mono text-xs text-muted">{waited > 0 ? `Waited ${formatDuration(waited)}` : 'Just started'}</span>
        <span className="text-xs text-muted">The trace keeps running on the server; the case stays in the list.</span>
      </div>
    </section>
  )
}
