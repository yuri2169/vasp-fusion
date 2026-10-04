import { CircleCheck, CircleDashed, Eye, LoaderCircle, OctagonAlert, Radar, TriangleAlert, type LucideIcon } from 'lucide-react'
import { ThreatChip } from '../components/ThreatChip'
import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../api/client'
import type { Chain, WatchChange, WatchItem, WatchState } from '../api/models'
import { useCheckWatch, useMarkWatchSeen, useUnwatch, useWatch, useWatchlist } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { inspectAddress } from '../lib/addresses'
import { CHAINS, EVM_TRACEABLE } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatDateTime } from '../lib/format'
import { plural } from '../overview/words'

const STATES: Record<WatchState, { words: string; Icon: LucideIcon; look: string }> = {
  changed: {
    words: 'Changed since last seen',
    Icon: TriangleAlert,
    look: 'border-fg bg-fg text-page',
  },
  unchanged: {
    words: 'No change',
    Icon: CircleCheck,
    look: 'border-rule-strong text-fg',
  },
  checking: {
    words: 'Checking',
    Icon: LoaderCircle,
    look: 'border-rule-strong bg-sunk text-fg',
  },
  not_traced: {
    words: 'Not traced yet',
    Icon: CircleDashed,
    look: 'border-dashed border-rule-strong text-muted',
  },
  failed: {
    words: 'Last check failed',
    Icon: OctagonAlert,
    look: 'border-seal-text text-seal-text',
  },
}

const CHANGE_ICON: Record<WatchChange['kind'], LucideIcon> = {
  new_alert: OctagonAlert,
  new_threat_link: OctagonAlert,
  new_exchange: TriangleAlert,
  new_activity: Radar,
}

function StateTag({ state }: { state: WatchState }) {
  const s = STATES[state]
  return (
    <span className={cx('inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-sm font-semibold', s.look)}>
      <s.Icon size={13} aria-hidden className={state === 'checking' ? 'motion-safe:animate-spin' : undefined} />
      {s.words}
    </span>
  )
}

function Row({ item }: { item: WatchItem }) {
  const check = useCheckWatch()
  const seen = useMarkWatchSeen()
  const unwatch = useUnwatch()
  const toast = useToast()
  const failed = (title: string) => (e: unknown) =>
    toast.show({
      kind: 'error',
      title,
      detail: e instanceof ApiError ? e.detail : undefined,
    })
  const busy = item.state === 'checking' || check.isPending

  return (
    <li className={cx('flex flex-col gap-3 border bg-surface p-4', item.state === 'changed' ? 'border-ink' : 'border-rule')}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <ChainBadge chain={item.chain} size="sm" />
          <AddressChip
            address={item.address}
            chain={item.chain}
            entity={item.label?.entity}
            tier={item.label?.tier}
            to={`/wallets/${item.chain}/${encodeURIComponent(item.address)}`}
          />
          <StateTag state={item.state} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {item.state === 'changed' && (
            <Button
              size="sm"
              disabled={seen.isPending}
              onClick={() =>
                seen.mutate(item.id, {
                  onSuccess: () => toast.show({ kind: 'success', title: 'Marked as seen' }),
                  onError: failed('Not marked as seen'),
                })
              }
            >
              Mark as seen
            </Button>
          )}
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              check.mutate(item.id, {
                onError: failed('The wallet could not be checked'),
              })
            }
          >
            {busy ? 'Checking…' : 'Check now'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={unwatch.isPending}
            onClick={() =>
              unwatch.mutate(item.id, {
                onSuccess: () => toast.show({ kind: 'success', title: 'Stopped watching' }),
                onError: failed('Still on the watchlist'),
              })
            }
          >
            Stop watching
          </Button>
        </div>
      </div>

      {item.note && <p className="text-base text-fg">{item.note}</p>}

      {item.changes.length > 0 && (
        <ul aria-label="What is new" className="flex flex-col gap-1.5 border-t border-rule pt-3">
          {item.changes.map((c, i) => {
            const Icon = CHANGE_ICON[c.kind]
            return (
              <li key={i} className={cx('flex gap-2 text-base', c.severity === 'high' ? 'font-medium text-seal-text' : 'text-fg')}>
                <Icon size={15} aria-hidden className="mt-0.5 shrink-0" />
                <span className="min-w-0 [overflow-wrap:anywhere]">
                  {c.threat && (
                    <span className="mr-2 inline-flex align-middle">
                      <ThreatChip tag={c.threat} size="sm" />
                    </span>
                  )}
                  {c.text}
                </span>
              </li>
            )
          })}
        </ul>
      )}
      {item.state === 'failed' && item.error && <p className="text-base text-seal-text [overflow-wrap:anywhere]">{item.error}</p>}
      {item.state === 'not_traced' && (
        <p className="text-base text-muted">This wallet has no trace to compare with. "Check now" traces it; that first result becomes what later checks are compared with.</p>
      )}

      <p className="tabular flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        <span>
          Watched since {formatDateTime(item.added_at)}
          {item.added_by ? ` by ${item.added_by}` : ''}
        </span>
        {item.last_checked_at && <span>Last traced {formatDateTime(item.last_checked_at)}</span>}
        {item.baseline_at && item.state === 'changed' && <span>Compared with the trace of {formatDateTime(item.baseline_at)}</span>}
        {item.case_id && (
          <Link to={`/cases/${encodeURIComponent(item.case_id)}`} className="underline decoration-rule-strong underline-offset-2 hover:text-fg">
            Open its case
          </Link>
        )}
      </p>
    </li>
  )
}

function AddForm() {
  const watch = useWatch()
  const toast = useToast()
  const [address, setAddress] = useState('')
  const [note, setNote] = useState('')
  const [evmChain, setEvmChain] = useState<Chain>('ethereum')
  const [error, setError] = useState<string | null>(null)
  const hintId = useId()
  const seen = inspectAddress(address)
  const isEvm = seen.state === 'valid' && seen.chain === 'ethereum'
  const chain = seen.state === 'valid' ? (isEvm ? evmChain : seen.chain) : null
  const whyNot = chain && !CHAINS[chain].traceable ? CHAINS[chain].whyNot : null
  const hint = error ?? (seen.state === 'invalid' ? seen.reason : whyNot)
  const field = 'h-9 rounded border border-rule-strong bg-surface px-2.5 text-base text-fg'

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (seen.state !== 'valid' || !chain || whyNot) return
    watch.mutate(
      { address: seen.normalized, chain, note: note.trim() || null },
      {
        onSuccess: () => {
          setAddress('')
          setNote('')
          setError(null)
          toast.show({ kind: 'success', title: 'Watching this wallet' })
        },
        onError: (err) => setError(err instanceof ApiError ? err.detail : 'The wallet could not be added. Try again.'),
      },
    )
  }

  return (
    <form onSubmit={submit} aria-label="Watch a wallet" className="mb-6 flex flex-col gap-2 panel p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-[20rem] flex-1 flex-col gap-1">
          <span className="eyebrow">Wallet address</span>
          <span className="flex items-center gap-2">
            <input
              value={address}
              onChange={(e) => {
                setAddress(e.target.value)
                setError(null)
              }}
              spellCheck={false}
              autoComplete="off"
              placeholder="Paste a Tron, EVM or Bitcoin address"
              aria-describedby={hint ? hintId : undefined}
              aria-invalid={seen.state === 'invalid' || undefined}
              className={`${field} min-w-0 flex-1 font-mono placeholder:font-sans`}
            />
            {chain && <ChainBadge chain={chain} />}
            {seen.state === 'typing' && seen.guess && <ChainBadge chain={seen.guess} tentative />}
          </span>
        </label>
        {isEvm && (
          <label className="flex flex-col gap-1">
            <span className="eyebrow">Chain</span>
            <select value={evmChain} onChange={(e) => setEvmChain(e.target.value as Chain)} className={field}>
              {EVM_TRACEABLE.map((c) => (
                <option key={c} value={c}>
                  {CHAINS[c].name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="flex min-w-[14rem] flex-1 flex-col gap-1">
          <span className="eyebrow">Why it is watched (optional)</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} className={field} />
        </label>
        <Button type="submit" variant="primary" disabled={seen.state !== 'valid' || Boolean(whyNot) || watch.isPending} icon={<Eye size={15} aria-hidden />}>
          Watch wallet
        </Button>
      </div>
      {hint && (
        <p id={hintId} role={error ? 'alert' : undefined} className="text-base text-seal-text">
          {hint}
        </p>
      )}
    </form>
  )
}

/** Wallets to keep an eye on. A check traces the wallet again and says what is new since the
 *  officer last marked it as seen: new transfers, a new exchange, a new alert. */
export function WatchlistPage() {
  const list = useWatchlist()
  const items = list.data?.items ?? []
  const changed = items.filter((w) => w.state === 'changed').length

  return (
    <>
      <PageHeader
        title="Watchlist"
        meta={list.data && items.length > 0 ? `${plural(items.length, 'wallet')} watched · ${changed ? `${plural(changed, 'wallet')} changed` : 'none changed'}` : undefined}
      >
        Wallets to check again. "Check now" traces a wallet afresh and compares it with the trace you last marked as seen. Nothing is checked in the background.
      </PageHeader>
      <AddForm />
      {list.isError ? (
        <ErrorState title="The watchlist could not be loaded" detail={list.error instanceof ApiError ? list.error.detail : 'Try again.'} onRetry={() => void list.refetch()} />
      ) : !list.data ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton width="70%" />
          <Skeleton width="50%" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState title="No wallet is being watched" icon={<Eye size={22} aria-hidden />}>
          Add a wallet above, or use "Watch this wallet" on a wallet's page. A watched wallet that moves, reaches a new exchange or raises an alert is listed here and on the
          dashboard.
        </EmptyState>
      ) : (
        <ul aria-label="Watched wallets" className="flex flex-col gap-3">
          {[...items]
            .sort((a, b) => Number(b.state === 'changed') - Number(a.state === 'changed'))
            .map((w) => (
              <Row key={w.id} item={w} />
            ))}
        </ul>
      )}
    </>
  )
}
