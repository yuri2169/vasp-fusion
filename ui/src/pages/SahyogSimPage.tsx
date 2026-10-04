import { ArrowRight, TriangleAlert } from 'lucide-react'
import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router'
import { ApiError } from '../api/client'
import type { ComplaintStatus, ComplaintWallet, ReplyStatus, SimRequest } from '../api/models'
import { useFileComplaint, useSahyogSim, useSimReply } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { PageHeader } from '../components/PageHeader'
import { RiskTag } from '../components/RiskTag'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { StatusTag } from '../desk/StatusTag'
import { ASK_WORDS } from '../desk/status'
import { cx } from '../lib/cx'
import { formatConfidence, formatDateTime } from '../lib/format'

const NOTICE = 'A simulator for demonstration. Not the SAHYOG portal.'

const CATEGORY_WORDS: Record<string, string> = {
  investment_fraud: 'Investment fraud',
  job_fraud: 'Job or task fraud',
  impersonation: 'Impersonation',
  phishing: 'Phishing',
  ransomware: 'Ransomware',
  extortion: 'Extortion',
  loan_app: 'Loan app',
  other: 'Other',
}

/** What each button does on the exchange's behalf, and the toast that confirms it. */
const REPLIES: Record<ReplyStatus, { button: string; done: string; danger?: boolean }> = {
  acknowledged: { button: 'Acknowledge', done: 'Acknowledged' },
  answered: { button: 'Reply with records', done: 'Replied with records' },
  freeze_confirmed: { button: 'Confirm freeze', done: 'Freeze confirmed' },
  refused: { button: 'Refuse', done: 'Refused', danger: true },
}

const field = 'h-9 w-full min-w-0 rounded-sm border border-ink-dim bg-surface px-2.5 text-base text-ink placeholder:text-ink-soft'

function Field({ label, hint, optional, children }: { label: string; hint?: string; optional?: boolean; children: (id: string, hintId?: string) => ReactNode }) {
  const id = useId()
  const hintId = hint ? `${id}-hint` : undefined
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium text-ink">
          {label}
        </label>
        {optional && <span className="text-sm text-ink-soft">optional</span>}
      </div>
      {children(id, hintId)}
      {hint && (
        <p id={hintId} className="text-sm text-ink-soft">
          {hint}
        </p>
      )}
    </div>
  )
}

const newRef = () => `SIM-${new Date().getFullYear()}-${String(Math.floor(1000 + Math.random() * 9000))}`

/** The portal's side of the intake: the fields the contract asks for, and "File complaint". */
function ComplaintForm({ categories }: { categories: string[] }) {
  const file = useFileComplaint()
  const toast = useToast()
  const [ref, setRef] = useState(newRef)
  const [agency, setAgency] = useState('Cyber Crime PS (simulated)')
  const [officer, setOfficer] = useState('SI, Cyber Cell (simulated)')
  const [wallets, setWallets] = useState('')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState('')
  const [category, setCategory] = useState('investment_fraud')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const list = wallets
      .split(/[\s,]+/)
      .map((a) => a.trim())
      .filter(Boolean)
    if (list.length === 0) return setError('Give at least one wallet address, one per line.')
    const lost = amount.replace(/[₹,\s]/g, '')
    if (lost && !/^\d+(\.\d{1,2})?$/.test(lost)) return setError('Write the amount lost in rupees as a number, for example 250000.')
    setError(null)
    file.mutate(
      {
        complaint_ref: ref.trim(),
        agency: agency.trim(),
        officer: officer.trim(),
        wallets: list.map((address) => ({ address })),
        category: category as never,
        amount_lost_inr: lost ? Number(lost) : null,
        incident_date: date || null,
        note: note.trim() || null,
      },
      {
        onSuccess: (c) => {
          const refused = c.wallets.filter((w) => !w.accepted).length
          toast.show({
            kind: 'success',
            title: 'Complaint filed',
            detail: `${c.wallets.length - refused} wallet${c.wallets.length - refused === 1 ? '' : 's'} sent for tracing${refused ? `, ${refused} refused` : ''}.`,
          })
          setRef(newRef())
          setWallets('')
          setNote('')
        },
        onError: (err) => setError(err instanceof ApiError ? err.detail : 'The complaint could not be filed. Try again.'),
      },
    )
  }

  return (
    <form onSubmit={submit} aria-label="File a complaint" className="flex flex-col gap-3 panel p-4">
      <h2 className="eyebrow">File a complaint</h2>
      <p className="-mt-1 text-sm text-ink-soft">What the portal would send. Filing it opens one case per wallet and starts each trace; nobody touches the tool.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Complaint reference" hint="The NCRP / 1930 acknowledgement number.">
          {(id, hintId) => <input id={id} aria-describedby={hintId} required value={ref} onChange={(e) => setRef(e.target.value)} className={cx(field, 'font-mono')} autoComplete="off" />}
        </Field>
        <Field label="Fraud category">
          {(id) => (
            <select id={id} value={category} onChange={(e) => setCategory(e.target.value)} className={field}>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {CATEGORY_WORDS[c] ?? c}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label="Reporting agency">{(id) => <input id={id} required value={agency} onChange={(e) => setAgency(e.target.value)} className={field} autoComplete="off" />}</Field>
        <Field label="Reporting officer">{(id) => <input id={id} required value={officer} onChange={(e) => setOfficer(e.target.value)} className={field} autoComplete="off" />}</Field>
      </div>
      <Field label="Wallet addresses" hint="One per line. The chain is read from each address.">
        {(id, hintId) => (
          <textarea
            id={id}
            aria-describedby={hintId}
            rows={3}
            value={wallets}
            onChange={(e) => setWallets(e.target.value)}
            spellCheck={false}
            className={cx(field, 'h-auto py-2 font-mono')}
            placeholder="TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c"
          />
        )}
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Amount lost, in rupees" optional>
          {(id) => <input id={id} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} className={cx(field, 'font-mono')} autoComplete="off" />}
        </Field>
        <Field label="Date of the incident" optional>
          {(id) => <input id={id} type="date" value={date} onChange={(e) => setDate(e.target.value)} className={cx(field, 'font-mono')} />}
        </Field>
      </div>
      <Field label="Note" optional>
        {(id) => <input id={id} value={note} onChange={(e) => setNote(e.target.value)} className={field} autoComplete="off" />}
      </Field>
      {error && (
        <p role="alert" className="text-base font-medium text-danger">
          {error}
        </p>
      )}
      <div>
        <Button type="submit" variant="primary" disabled={file.isPending}>
          {file.isPending ? 'Filing…' : 'File complaint'}
        </Button>
      </div>
    </form>
  )
}

const STEPS = ['received', 'tracing', 'result'] as const
const STEP_WORDS = { received: 'Received', tracing: 'Tracing', result: 'Result' }

/** Where a complaint stands: three boxes in order, the reached ones filled in. */
function Progress({ status }: { status: ComplaintStatus['status'] }) {
  const at = STEPS.indexOf(status)
  return (
    <ol aria-label={`Status: ${STEP_WORDS[status]}`} className="flex items-center gap-1 text-sm">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-1">
          {i > 0 && <ArrowRight size={12} aria-hidden className="text-ink-soft" />}
          <span
            aria-current={i === at ? 'step' : undefined}
            className={cx('border px-1.5 py-0.5', i < at ? 'border-ink text-ink' : i === at ? 'border-ink bg-ink font-semibold text-surface' : 'border-dashed border-ink-dim text-ink-soft')}
          >
            {STEP_WORDS[s]}
          </span>
        </li>
      ))}
    </ol>
  )
}

function WalletLine({ w }: { w: ComplaintWallet }) {
  if (!w.accepted)
    return (
      <li className="flex flex-col gap-1 border-t border-rule-soft py-2 first:border-t-0">
        <span className="break-all font-mono text-sm text-ink">{w.address}</span>
        <span className="text-sm font-medium text-danger">Refused: {w.error}</span>
      </li>
    )
  const done = w.status === 'result'
  return (
    <li className="flex flex-col gap-1.5 border-t border-rule-soft py-2 first:border-t-0">
      <span className="flex flex-wrap items-center gap-2">
        {w.chain && <ChainBadge chain={w.chain} size="sm" />}
        {w.chain && <AddressChip address={w.address} chain={w.chain} actions="copy" />}
        {!done && <span className="text-sm text-ink-soft">{w.status === 'failed' ? `The trace failed: ${w.case_error ?? 'no reason recorded'}` : w.status === 'tracing' ? 'Being traced…' : 'Waiting its turn…'}</span>}
      </span>
      {done && (
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <OutcomeStamp outcome={w.outcome ?? null} status="done" vasp={w.top_vasp} confidence={w.confidence} />
          {w.top_vasp && w.confidence != null && <span className="text-sm text-ink-soft">confidence <span className="tabular font-mono text-ink">{formatConfidence(w.confidence)}</span></span>}
          <RiskTag risk={w.risk_class} score={w.risk_score} />
        </span>
      )}
      <span className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-soft">
        {w.case_id && (
          <Link to={`/cases/${encodeURIComponent(w.case_id)}`} className="font-medium text-ink underline decoration-ink-dim underline-offset-2 hover:decoration-ink">
            Open the case
          </Link>
        )}
        {w.request_ids.map((id) => (
          <Link key={id} to={`/requests/${encodeURIComponent(id)}`} className="font-mono text-ink underline decoration-ink-dim underline-offset-2 hover:decoration-ink">
            {id}
          </Link>
        ))}
        {w.result_sent_at && <span>Result handed back {formatDateTime(w.result_sent_at)}</span>}
      </span>
    </li>
  )
}

function Complaints({ items }: { items: ComplaintStatus[] }) {
  return (
    <section aria-label="Complaints filed" className="flex flex-col gap-2">
      <h2 className="eyebrow">Complaints filed</h2>
      {items.length === 0 ? (
        <EmptyState title="No complaint filed yet">File one above. Its wallets are traced without anyone touching the tool, and the result appears here.</EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((c) => (
            <li key={c.complaint_ref} data-testid="complaint" className="flex flex-col gap-2 panel p-4">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                <span className="flex flex-col">
                  <span className="font-mono text-base font-medium text-ink">{c.complaint_ref}</span>
                  <span className="text-sm text-ink-soft">
                    {c.agency} · {CATEGORY_WORDS[c.category] ?? c.category} · received {formatDateTime(c.received_at)}
                  </span>
                </span>
                <Progress status={c.status} />
              </div>
              <ul className="flex flex-col">
                {c.wallets.map((w) => (
                  <WalletLine key={w.address} w={w} />
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function RequestCard({ r }: { r: SimRequest }) {
  const reply = useSimReply()
  const toast = useToast()
  const send = (status: ReplyStatus) =>
    reply.mutate(
      { id: r.id, status, note: `${REPLIES[status].done} in the simulator, playing ${r.vasp}.` },
      {
        onSuccess: () => toast.show({ kind: 'success', title: REPLIES[status].done, detail: `The request desk now reads this for ${r.reference}.` }),
        onError: (e) => toast.show({ kind: 'error', title: 'The reply was not recorded', detail: e instanceof ApiError ? e.detail : undefined }),
      },
    )
  return (
    <li data-testid="sim-request" className="flex flex-col gap-2.5 panel p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <span className="flex flex-col">
          <Link to={`/requests/${encodeURIComponent(r.id)}`} className="font-mono text-base font-medium text-ink underline decoration-ink-dim underline-offset-2 hover:decoration-ink">
            {r.reference}
          </Link>
          <span className="text-sm text-ink-soft">
            To <span className="font-medium text-ink">{r.vasp}</span> · {r.wallets} wallet{r.wallets === 1 ? '' : 's'}
            {r.sent_at && ` · sent ${formatDateTime(r.sent_at)}`}
          </span>
        </span>
        <StatusTag status={r.status} />
      </div>
      <p className="text-sm text-ink">Asks for: {r.asks.map((a) => ASK_WORDS[a]).join(', ')}.</p>
      {r.allowed_replies.length > 0 ? (
        <div role="group" aria-label={`Reply as ${r.vasp}`} className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-ink-soft">Reply as {r.vasp}:</span>
          {r.allowed_replies.map((s) => (
            <Button key={s} size="sm" variant={REPLIES[s].danger ? 'danger' : 'secondary'} disabled={reply.isPending} onClick={() => send(s)}>
              {REPLIES[s].button}
            </Button>
          ))}
        </div>
      ) : (
        <p className="text-sm text-ink-soft">Closed: no further reply can follow.</p>
      )}
    </li>
  )
}

function Requests({ items }: { items: SimRequest[] }) {
  return (
    <section aria-label="Requests received" className="flex flex-col gap-2">
      <h2 className="eyebrow">Requests received</h2>
      <p className="-mt-1 text-sm text-ink-soft">The outbox as the portal would see it. The buttons play the exchange; each reply arrives at the request desk through the same route a real reply would.</p>
      {items.length === 0 ? (
        <EmptyState
          title="No request has been sent yet"
          action={
            <Link to="/desk" className="text-base font-medium text-ink underline decoration-ink-dim underline-offset-2 hover:decoration-ink">
              Open the request desk
            </Link>
          }
        >
          Draft a request to an exchange on the request desk, approve it and mark it as sent. It then appears here.
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {items.map((r) => (
            <RequestCard key={r.id} r={r} />
          ))}
        </ul>
      )}
    </section>
  )
}

/** The simulated portal: file a complaint on the left, answer requests as an exchange on the right.
 *  The banner never goes away: this is a simulator for demonstration, not the SAHYOG portal. */
export function SahyogSimPage() {
  const q = useSahyogSim()
  const d = q.data
  return (
    <>
      <div role="note" aria-label="Simulator notice" className="mb-4 flex items-start gap-3 border-2 border-dashed border-ink bg-surface-2 px-4 py-3">
        <TriangleAlert size={18} aria-hidden className="mt-0.5 shrink-0 text-ink" />
        <p className="text-base text-ink">
          <strong className="font-semibold">{d?.notice ?? NOTICE}</strong> SAHYOG's own interface is not public. This screen plays the portal's side of a proposed
          contract, so the round trip can be shown: a complaint in, the result back, a request out, the exchange's reply in. Nothing leaves this installation.
        </p>
      </div>
      <PageHeader eyebrow="Demonstration" title="SAHYOG simulator">
        File a complaint as the portal would, watch its wallets being traced, then answer the requests that come back as the exchange would.
      </PageHeader>

      {q.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <Skeleton width="40%" />
          <Skeleton lines={5} />
        </div>
      ) : q.isError || !d ? (
        <ErrorState title="The simulator could not be read" detail={q.error instanceof ApiError ? q.error.detail : 'Reload the page to try again.'} onRetry={() => void q.refetch()} />
      ) : !d.enabled ? (
        <EmptyState title="The simulator is switched off">{d.why_disabled ?? 'No intake key is set on this installation.'}</EmptyState>
      ) : (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <div className="flex flex-col gap-5">
            <ComplaintForm categories={d.categories.length ? d.categories : Object.keys(CATEGORY_WORDS)} />
            <Complaints items={d.complaints} />
          </div>
          <Requests items={d.requests} />
        </div>
      )}
    </>
  )
}
