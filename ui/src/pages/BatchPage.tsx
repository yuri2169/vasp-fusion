import { Download, Upload } from 'lucide-react'
import { useId, useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { api } from '../api/api'
import { ApiError } from '../api/client'
import type { BatchDetail, BatchProgress, BatchRow, BatchSummary } from '../api/models'
import { useBatch, useBatches, useUploadBatch } from '../api/queries'
import { DEFAULT_HOPS, DEFAULT_WALLETS, walletBudgetError } from '../case/rules'
import { HopLimit, WalletBudget } from '../case/TraceAgain'
import { Button, buttonClass } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DataTable, type Column } from '../components/DataTable'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { PageHeader } from '../components/PageHeader'
import { RiskTag } from '../components/RiskTag'
import { Skeleton } from '../components/Skeleton'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatConfidence, formatDateTime, formatNumber, formatPercent, truncateMiddle } from '../lib/format'
import { Ledger, Panel } from '../overview/parts'

/** What one upload may hold (vaspfusion/batch.py). The server checks both again. */
export const MAX_ROWS = 2000

const field = 'w-full min-w-0 rounded border border-rule-strong bg-surface px-3 text-base text-fg placeholder:text-muted'

const plural = (n: number, word: string) => `${formatNumber(n)} ${word}${n === 1 ? '' : 's'}`

/** "4 worker processes" / "the server process, one wallet at a time". */
export const tracedBy = (workers: number) =>
  workers > 1 ? `${formatNumber(workers)} worker processes` : workers === 1 ? '1 worker process' : 'the server process, one wallet at a time'

/** How far a batch has got, in one sentence. */
export function progressSentence(p: BatchProgress): string {
  if (p.accepted === 0) return 'No row could be traced. Each row says why.'
  const closed = p.done + p.failed
  if (p.finished) return `All ${plural(p.accepted, 'wallet')} traced${p.failed ? `, ${formatNumber(p.failed)} of them failed` : ''}.`
  return `${formatNumber(closed)} of ${plural(p.accepted, 'wallet')} traced, ${formatNumber(p.running)} being traced now, ${formatNumber(p.queued)} waiting.`
}

/** The queue as one ruled bar: traced, being traced, waiting. Told apart by fill, and by the legend's words. */
function ProgressBar({ p }: { p: BatchProgress }) {
  const total = Math.max(1, p.accepted)
  const parts = [
    { key: 'done', n: p.done, name: 'Traced', fill: 'bg-ink' },
    { key: 'failed', n: p.failed, name: 'Failed', fill: 'bg-danger' },
    { key: 'running', n: p.running, name: 'Being traced', fill: 'hatch' },
    { key: 'queued', n: p.queued, name: 'Waiting', fill: 'bg-surface-3' },
  ]
  return (
    <div className="flex flex-col gap-2">
      <div
        role="progressbar"
        aria-label="Wallets traced"
        aria-valuemin={0}
        aria-valuemax={p.accepted}
        aria-valuenow={p.done + p.failed}
        aria-valuetext={progressSentence(p)}
        className="flex h-3 w-full overflow-hidden border border-ink-dim bg-surface-3"
      >
        {parts.map((s) => s.n > 0 && <span key={s.key} data-part={s.key} className={cx('h-full', s.fill)} style={{ width: `${(s.n / total) * 100}%` }} />)}
      </div>
      <ul className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-ink-soft">
        {parts.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden className={cx('inline-block h-2.5 w-2.5 border border-ink-dim', s.fill)} />
            {s.name} <span className="tabular font-mono text-ink">{formatNumber(s.n)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

const OUTCOMES: { key: string; name: string; note: string }[] = [
  { key: 'ATTRIBUTED', name: 'Named an exchange', note: 'A request can be drafted to it.' },
  { key: 'INSUFFICIENT_EVIDENCE', name: 'No exchange named', note: 'The case says why, and what would change it.' },
  { key: 'SANCTIONED_OR_MIXER_REACHED', name: 'Sanctioned or mixer', note: 'The money reached a listed address or a mixer.' },
]

function note(r: BatchRow): string {
  if (r.error) return r.error
  if (r.duplicate_of != null) return `The same wallet as row ${r.duplicate_of}: one case, traced once.`
  if (r.budget_ended) return 'The trace budget, not the evidence, ended this trace. Open the case to trace it with a larger one.'
  return ''
}

const columns: Column<BatchRow>[] = [
  { key: 'row', header: 'Row', align: 'right', width: 56, sortValue: (r) => r.row, cell: (r) => <span className="tabular font-mono text-sm text-ink-soft">{r.row}</span> },
  {
    key: 'wallet',
    header: 'Wallet',
    sortValue: (r) => r.address,
    cell: (r) => (
      // shortened to fit a row; the whole address is the link's name, its tooltip, and in the CSV
      <span className="flex items-center gap-2 whitespace-nowrap">
        {r.chain && r.chain in CHAINS && <ChainBadge chain={r.chain as keyof typeof CHAINS} size="sm" />}
        {r.case_url ? (
          <Link to={r.case_url} title={r.address} aria-label={r.address} className="font-mono text-sm text-ink underline decoration-ink-dim underline-offset-2 hover:decoration-ink">
            {truncateMiddle(r.address, 8, 8)}
          </Link>
        ) : (
          <span title={r.address} className="font-mono text-sm text-ink-soft">
            {r.address ? truncateMiddle(r.address, 8, 8) : '(empty)'}
          </span>
        )}
      </span>
    ),
  },
  { key: 'ref', header: 'Case reference', sortValue: (r) => r.case_ref ?? null, cell: (r) => r.case_ref ?? <span className="text-ink-dim">-</span> },
  {
    key: 'result',
    header: 'Result',
    sortValue: (r) => r.outcome ?? r.status ?? (r.accepted ? 'z' : 'refused'),
    cell: (r) =>
      r.accepted ? (
        <OutcomeStamp outcome={r.outcome ?? null} status={r.status ?? 'queued'} vasp={r.top_vasp} />
      ) : (
        <span className="inline-flex h-6 items-center border border-dashed border-danger px-1.5 text-sm font-semibold text-danger">Refused</span>
      ),
  },
  {
    key: 'hops',
    header: 'Hops',
    align: 'right',
    width: 64,
    sortValue: (r) => r.hops ?? null,
    cell: (r) => (r.hops != null ? <span className="tabular font-mono">{r.hops}</span> : <span className="text-ink-dim">-</span>),
  },
  {
    key: 'share',
    header: 'Share',
    align: 'right',
    width: 72,
    sortValue: (r) => r.share_of_funds ?? null,
    cell: (r) => (r.share_of_funds != null ? <span className="tabular font-mono">{formatPercent(r.share_of_funds)}</span> : <span className="text-ink-dim">-</span>),
  },
  {
    key: 'confidence',
    header: 'Confidence',
    align: 'right',
    width: 96,
    sortValue: (r) => r.confidence ?? null,
    cell: (r) => (r.confidence != null ? <span className="tabular font-mono">{formatConfidence(r.confidence)}</span> : <span className="text-ink-dim">-</span>),
  },
  { key: 'risk', header: 'Risk', width: 104, sortValue: (r) => r.risk_class ?? null, cell: (r) => (r.risk_class ? <RiskTag risk={r.risk_class} /> : <span className="text-ink-dim">-</span>) },
  { key: 'note', header: 'Note', cell: (r) => <span className={cx('text-sm', r.error ? 'text-danger' : 'text-ink-soft')}>{note(r)}</span> },
]

function Results({ b }: { b: BatchDetail }) {
  const p = b.progress
  return (
    <div className="flex flex-col gap-4">
      <Ledger
        label="The batch in counts"
        entries={[
          { key: 'rows', name: 'Rows uploaded', value: formatNumber(p.total), note: p.duplicates ? `${plural(p.duplicates, 'row')} repeated a wallet` : 'Each wallet is one case' },
          ...OUTCOMES.map((o) => ({ key: o.key, name: o.name, value: formatNumber(p.by_outcome[o.key] ?? 0), note: o.note })),
          { key: 'refused', name: 'Rows refused', value: formatNumber(p.refused), note: 'Each says why; the others went on.', alert: p.refused > 0 },
        ]}
      />

      <Panel title="Progress" note={`Traced by ${tracedBy(b.workers)}. Each wallet may read ${plural(b.max_wallets, 'wallet')} per direction, ${plural(b.max_hops, 'hop')} out${b.max_seconds ? `, for ${formatNumber(b.max_seconds)} seconds` : ''}.`}>
        <p role="status" className="text-md text-ink">
          {progressSentence(p)}
        </p>
        <ProgressBar p={p} />
      </Panel>

      <Panel title="Results" note="One line per uploaded row, in upload order. Proximity (hops, share of the funds) and confidence are separate figures. A refused row is kept, with its reason.">
        <DataTable caption="Batch results" columns={columns} rows={b.rows} rowKey={(r) => String(r.row)} empty="This batch holds no row." maxHeight={640} />
      </Panel>
    </div>
  )
}

/** One batch: how far the queue has got, and the result table. */
export function BatchPage() {
  const { id = '' } = useParams()
  const q = useBatch(id)
  const b = q.data
  return (
    <>
      <PageHeader
        eyebrow="Batch"
        title={b?.name ?? (b ? `Batch of ${plural(b.progress.total, 'row')}` : 'Batch')}
        meta={b && `Uploaded ${formatDateTime(b.created_at)}${b.created_by ? ` by ${b.created_by}` : ''} · id ${b.id}`}
        actions={
          b && (
            <a href={api.batchCsvUrl(b.id)} download className={buttonClass('secondary')}>
              <Download size={14} aria-hidden />
              Download results (CSV)
            </a>
          )
        }
      />
      {q.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <Skeleton width="40%" />
          <Skeleton lines={5} />
        </div>
      ) : q.isError || !b ? (
        <ErrorState title="The batch could not be read" detail={q.error instanceof ApiError ? q.error.detail : 'Reload the page to try again.'} onRetry={() => void q.refetch()} />
      ) : (
        <Results b={b} />
      )}
    </>
  )
}

function Earlier({ items }: { items: BatchSummary[] }) {
  return (
    <ul className="flex flex-col">
      {items.map((b) => (
        <li key={b.id} className="border-t border-rule-soft first:border-t-0">
          <Link to={`/batch/${encodeURIComponent(b.id)}`} className="row-hover flex flex-wrap items-baseline gap-x-4 gap-y-1 px-1 py-2.5">
            <span className="text-base font-medium text-ink">{b.name ?? `Batch ${b.id}`}</span>
            <span className="font-mono text-sm text-ink-soft">{formatDateTime(b.created_at)}</span>
            <span className="ml-auto text-sm text-ink-soft">{progressSentence(b.progress)}</span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

/** Upload a batch: a CSV file (or pasted lines) of wallets, traced through the same queue as every case. */
export function BatchUploadPage() {
  const navigate = useNavigate()
  const upload = useUploadBatch()
  const batches = useBatches()
  const ids = { name: useId(), file: useId(), text: useId() }

  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [fileName, setFileName] = useState('')
  const [hops, setHops] = useState(DEFAULT_HOPS)
  const [wallets, setWallets] = useState(String(DEFAULT_WALLETS))

  const lines = text.split(/\r?\n/).filter((l) => l.trim()).length
  const budgetError = walletBudgetError(wallets)
  const tooMany = lines > MAX_ROWS + 1 ? `This holds ${formatNumber(lines)} lines; one batch takes at most ${formatNumber(MAX_ROWS)} rows. Split the file.` : null
  const ready = lines > 0 && !budgetError && !tooMany && !upload.isPending

  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    upload.reset()
    setFileName(file.name)
    if (!name.trim()) setName(file.name.replace(/\.[^.]+$/, ''))
    void file.text().then(setText)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!ready) return
    upload.mutate(
      { csv: text, ...(name.trim() && { name: name.trim() }), max_hops: hops, max_wallets: Number(wallets) },
      { onSuccess: (b) => navigate(`/batch/${encodeURIComponent(b.id)}`) },
    )
  }

  return (
    <>
      <PageHeader eyebrow="Cases" title="Trace a batch">
        Many wallets in one upload. Each row is checked on its own: a row that cannot be traced is reported with its reason and never stops the others. A wallet that already has a
        case is linked to it, not traced again.
      </PageHeader>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,640px)_minmax(0,1fr)]">
        <form aria-label="Upload a batch" onSubmit={submit} noValidate className="panel flex flex-col">
          <div className="flex flex-col gap-4 px-5 py-5">
            <h2 className="eyebrow">The wallets</h2>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={ids.file} className="text-base font-medium text-fg">
                CSV file
              </label>
              <input id={ids.file} type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" onChange={pick} className="text-base text-fg file:mr-3 file:h-8 file:border file:border-ink file:bg-surface file:px-3 file:text-base file:font-medium file:text-ink" />
              <p className="text-sm text-muted">
                Columns <span className="font-mono text-fg">address, chain, case_ref</span>. A header line is optional; only the address is required. Up to {formatNumber(MAX_ROWS)} rows.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={ids.text} className="text-base font-medium text-fg">
                Or paste the lines
              </label>
              <textarea
                id={ids.text}
                value={text}
                onChange={(e) => {
                  setText(e.target.value)
                  setFileName('')
                  upload.reset()
                }}
                rows={7}
                spellCheck={false}
                autoCapitalize="off"
                placeholder={'address,chain,case_ref\nT…,tron,CC/2026/118\n0x…,ethereum,'}
                aria-invalid={tooMany ? true : undefined}
                className={cx(field, 'py-2 font-mono text-sm')}
              />
              <p className={cx('text-sm', tooMany ? 'font-medium text-seal-text' : 'text-muted')}>
                {tooMany ?? (lines > 0 ? `${plural(lines, 'line')}${fileName ? ` read from ${fileName}` : ''}. The file is read here and sent as text.` : 'One wallet per line.')}
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor={ids.name} className="text-base font-medium text-fg">
                Name <span className="text-sm font-normal text-muted">optional</span>
              </label>
              <input id={ids.name} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoComplete="off" placeholder="Complaint 14, wallets from the bank statement" className={cx(field, 'h-10')} />
            </div>
          </div>

          <div className="flex flex-col gap-4 border-t border-rule px-5 py-5">
            <h2 className="eyebrow">The trace budget, for each wallet</h2>
            <div className="flex flex-col gap-1.5">
              <span className="text-base font-medium text-fg">How many hops to follow the money</span>
              <HopLimit value={hops} onChange={setHops} name="batch-max-hops" />
            </div>
            <WalletBudget value={wallets} onChange={setWallets} />
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-rule bg-sunk px-5 py-4">
            <Button type="submit" variant="primary" disabled={!ready} icon={<Upload size={14} aria-hidden />}>
              {upload.isPending ? 'Uploading…' : 'Upload and trace'}
            </Button>
            {upload.isError && (
              <p role="alert" className="min-w-0 flex-1 text-base font-medium text-seal-text">
                {upload.error instanceof ApiError ? upload.error.detail : 'The batch could not be uploaded. Try again.'}
              </p>
            )}
          </div>
        </form>

        <Panel title="Earlier batches" note="Newest first. A batch keeps its rows and their results.">
          {batches.isPending ? (
            <Skeleton lines={3} />
          ) : batches.isError ? (
            <p className="text-base text-fg">{batches.error instanceof ApiError ? batches.error.detail : 'The batches could not be loaded.'}</p>
          ) : batches.data.items.length === 0 ? (
            <EmptyState title="No batch yet">Upload a file to trace many wallets at once.</EmptyState>
          ) : (
            <Earlier items={batches.data.items} />
          )}
        </Panel>
      </div>
    </>
  )
}
