import { useId, useState } from 'react'
import { ApiError } from '../api/client'
import type { CaseDetail } from '../api/models'
import { useOpenCase } from '../api/queries'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { cx } from '../lib/cx'
import { DEFAULT_HOPS, DEFAULT_WALLETS, HOP_LIMITS, walletBudgetError } from './rules'

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

/** The wallet budget: how many wallets a trace may read per direction. Used on intake, on a batch and here. */
export function WalletBudget({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  const id = useId()
  const error = walletBudgetError(value)
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-base font-medium text-fg">
        Wallets read per direction
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="numeric"
        autoComplete="off"
        aria-invalid={error ? true : undefined}
        aria-describedby={`${id}-note`}
        className={cx('h-10 w-32 rounded border bg-surface px-3 font-mono text-base text-fg', error ? 'border-seal-text' : 'border-rule-strong')}
      />
      <p id={`${id}-note`} className={cx('text-sm', error ? 'font-medium text-seal-text' : 'text-muted')}>
        {error ??
          `${DEFAULT_WALLETS} is usual. The wallets holding the most of the money are read first, and the case says so when the budget, not the evidence, ended the trace.`}
      </p>
    </div>
  )
}

/** Trace the wallet again (new transfers, a deeper hop limit, a changed label database).
 *  The result on screen stays until the new one is ready. */
export function TraceAgain({ c, open, onClose, onStarted }: { c: CaseDetail; open: boolean; onClose: () => void; onStarted: () => void }) {
  const [hops, setHops] = useState(c.provenance.input?.max_hops ?? DEFAULT_HOPS)
  const [wallets, setWallets] = useState(String(c.provenance.budget?.max_wallets ?? DEFAULT_WALLETS))
  const openCase = useOpenCase()

  const start = () =>
    openCase.mutate(
      { address: c.address, chain: c.chain, max_hops: hops, ...(Number(wallets) !== DEFAULT_WALLETS && { max_wallets: Number(wallets) }), refresh: true },
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
          <Button onClick={start} disabled={openCase.isPending || walletBudgetError(wallets) !== null}>
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
      <div className="mt-4">
        <WalletBudget value={wallets} onChange={setWallets} />
      </div>
      {openCase.isError && (
        <p role="alert" className="mt-4 rounded border border-seal-text bg-seal-wash px-3 py-2 text-fg">
          {openCase.error instanceof ApiError ? openCase.error.detail : 'The trace could not be started. Try again.'}
        </p>
      )}
    </Dialog>
  )
}
