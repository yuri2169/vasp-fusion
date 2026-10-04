import { useState } from 'react'
import { ApiError } from '../api/client'
import type { CaseDetail } from '../api/models'
import { useOpenCase } from '../api/queries'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { cx } from '../lib/cx'
import { DEFAULT_HOPS, HOP_LIMITS } from './rules'

/** How far to follow the money: 1 to 5 hops out. One radio group, used on intake and here. */
export function HopLimit({ value, onChange, name }: { value: number; onChange: (hops: number) => void; name: string }) {
  return (
    <div role="radiogroup" aria-label="Hop limit" className="inline-flex self-start rounded border border-rule-strong">
      {HOP_LIMITS.map((hops) => (
        <label
          key={hops}
          className={cx(
            'relative inline-flex h-9 min-w-10 cursor-pointer items-center justify-center border-l border-rule-strong px-3 font-mono text-base first:border-l-0',
            'has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus',
            value === hops ? 'bg-fg text-page' : 'bg-surface text-fg hover:bg-sunk',
          )}
        >
          <input
            type="radio"
            name={name}
            value={hops}
            checked={value === hops}
            onChange={() => onChange(hops)}
            aria-label={`${hops} hop${hops === 1 ? '' : 's'}`}
            className="absolute inset-0 cursor-pointer opacity-0"
          />
          {hops}
        </label>
      ))}
    </div>
  )
}

/** Trace the wallet again (new transfers, a deeper hop limit, a changed label database).
 *  The result on screen stays until the new one is ready. */
export function TraceAgain({ c, open, onClose, onStarted }: { c: CaseDetail; open: boolean; onClose: () => void; onStarted: () => void }) {
  const [hops, setHops] = useState(c.provenance.input?.max_hops ?? DEFAULT_HOPS)
  const openCase = useOpenCase()

  const start = () =>
    openCase.mutate(
      { address: c.address, chain: c.chain, max_hops: hops, refresh: true },
      {
        onSuccess: () => {
          onStarted()
          onClose()
        },
      },
    )

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Trace this wallet again?"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Keep this result
          </Button>
          <Button onClick={start} disabled={openCase.isPending}>
            {openCase.isPending ? 'Starting…' : 'Trace again'}
          </Button>
        </>
      }
    >
      <p>
        The wallet’s transfers are read again and the result replaces this one. Until the new result is ready, this one stays on screen. The case
        reference and complaint number are kept.
      </p>
      <p className="mb-2 mt-4 font-medium">How many hops to follow the money</p>
      <HopLimit value={hops} onChange={setHops} name="trace-again-hops" />
      {openCase.isError && (
        <p role="alert" className="mt-4 rounded border border-seal-text bg-seal-wash px-3 py-2 text-fg">
          {openCase.error instanceof ApiError ? openCase.error.detail : 'The trace could not be started. Try again.'}
        </p>
      )}
    </Dialog>
  )
}
