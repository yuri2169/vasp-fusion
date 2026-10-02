import { CornerDownLeft } from 'lucide-react'
import { useId, useState, type FormEvent, type InputHTMLAttributes, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import type { CaseSummary, Chain } from '../api/models'
import { useCases, useOpenCase } from '../api/queries'
import { DEFAULT_HOPS } from '../case/rules'
import { HopLimit } from '../case/TraceAgain'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { inspectAddress } from '../lib/addresses'
import { CHAINS, EVM_TRACEABLE } from '../lib/chains'
import { cx } from '../lib/cx'
import { truncateMiddle } from '../lib/format'

const pad = (n: number) => String(n).padStart(2, '0')
const today = () => {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** "40,50,000", "₹ 4050000", "4050000.50" → a number; anything else → null. */
function rupees(text: string): number | null {
  const digits = text.replace(/[₹,\s]/g, '')
  return /^\d+(\.\d{1,2})?$/.test(digits) ? Number(digits) : null
}

const inputClass = (invalid?: boolean) =>
  cx(
    'h-10 w-full min-w-0 rounded border bg-surface px-3 text-sm text-fg placeholder:text-muted',
    invalid ? 'border-seal-text' : 'border-rule-strong',
  )

/** A labelled field with one line under it: what is wrong, or what the field is for. */
function Field({
  label,
  hint,
  error,
  optional = true,
  className,
  children,
  ...input
}: {
  label: string
  hint?: string
  error?: string | null
  optional?: boolean
  children?: ReactNode
} & InputHTMLAttributes<HTMLInputElement>) {
  const id = useId()
  const noteId = `${id}-note`
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium text-fg">
          {label}
        </label>
        {optional && <span className="text-xs text-muted">optional</span>}
      </div>
      <div className="relative flex items-center">
        <input
          id={id}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? noteId : undefined}
          autoComplete="off"
          className={cx(inputClass(!!error), className)}
          {...input}
        />
        {children}
      </div>
      {(error || hint) && (
        <p id={noteId} className={cx('text-xs', error ? 'font-medium text-seal-text' : 'text-muted')}>
          {error || hint}
        </p>
      )}
    </div>
  )
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-4 border-t border-rule px-5 py-5 first:border-t-0">
      <legend className="eyebrow float-left mb-1 w-full">{title}</legend>
      {children}
    </fieldset>
  )
}

/** The demo cases the server holds, to pick a wallet from without typing one. */
function DemoCases({ onPick, picked }: { onPick: (c: CaseSummary) => void; picked: string }) {
  const cases = useCases()
  const demos = (cases.data?.items ?? []).filter((c) => c.demo)
  return (
    <section aria-label="Recorded demo cases" className="flex flex-col gap-3">
      <h2 className="eyebrow">Recorded demo cases</h2>
      <p className="max-w-prose text-sm text-muted">
        Real wallets, traced and stored, to see what a case looks like. Picking one fills in its address; nothing here alleges anything about its owner.
      </p>
      {cases.isPending && <Skeleton lines={3} />}
      {cases.isError && <p className="text-sm text-fg">{cases.error instanceof ApiError ? cases.error.detail : 'The demo cases could not be loaded.'}</p>}
      {cases.data && demos.length === 0 && <p className="text-sm text-fg">This server holds no demo case. Run make demo to record them.</p>}
      <ul className="flex max-h-[520px] flex-col gap-2 overflow-y-auto pr-1">
        {demos.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              aria-pressed={picked === c.address}
              onClick={() => onPick(c)}
              className={cx(
                'flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 rounded border bg-surface px-3 py-2.5 text-left hover:bg-sunk',
                picked === c.address ? 'border-fg' : 'border-rule',
              )}
            >
              <span className="text-sm font-medium text-fg">{c.case_ref ?? c.id}</span>
              <ChainBadge chain={c.chain} size="sm" />
              <span className="font-mono text-xs text-fg">{truncateMiddle(c.address)}</span>
              <span className="ml-auto">
                <OutcomeStamp outcome={c.outcome ?? null} status={c.status} vasp={c.top_vasp} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Open a case: the file's cover sheet. The wallet, the complaint it belongs to, and how far
 *  to follow the money. "Trace wallet" starts the trace and opens the case to watch it. */
export function NewCasePage() {
  const navigate = useNavigate()
  const openCase = useOpenCase()
  const { show } = useToast()

  const [address, setAddress] = useState('')
  const [evmChain, setEvmChain] = useState<Chain>('ethereum')
  const [caseRef, setCaseRef] = useState('')
  const [complaint, setComplaint] = useState('')
  const [amount, setAmount] = useState('')
  const [date, setDate] = useState('')
  const [hops, setHops] = useState(DEFAULT_HOPS)
  const [refresh, setRefresh] = useState(false)

  const seen = inspectAddress(address)
  const isEvm = seen.state === 'valid' && CHAINS[seen.chain].family === 'evm'
  const chain: Chain | null = seen.state === 'valid' ? (isEvm ? evmChain : seen.chain) : null
  const untraceable = chain && !CHAINS[chain].traceable ? (CHAINS[chain].whyNot ?? `${CHAINS[chain].name} wallets cannot be traced yet.`) : null
  const addressError = seen.state === 'invalid' ? seen.reason : untraceable

  const amountValue = amount.trim() ? rupees(amount) : null
  const amountError = amount.trim() && amountValue === null ? 'Write the amount in rupees, in digits: 4050000 or 40,50,000.' : null
  const dateError = date && date > today() ? 'The incident cannot be in the future.' : null
  const ready = seen.state === 'valid' && chain !== null && !untraceable && !amountError && !dateError && !openCase.isPending

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!ready || seen.state !== 'valid' || !chain) return
    openCase.mutate(
      {
        address: seen.normalized,
        chain,
        ...(caseRef.trim() && { case_ref: caseRef.trim() }),
        ...(complaint.trim() && { complaint_no: complaint.trim() }),
        ...(amountValue !== null && { amount_lost_inr: amountValue }),
        ...(date && { incident_date: date }),
        max_hops: hops,
        refresh,
      },
      {
        onSuccess: (opened) => {
          if (opened.status === 'done')
            show({ title: 'This wallet already has a case', detail: 'It is shown as it was last traced. Use Trace again to read the chain afresh.' })
          // `watched`: this officer started the trace, so the page extends the rail when the result lands.
          navigate(`/cases/${encodeURIComponent(opened.id)}`, { state: { watched: opened.status !== 'done' } })
        },
      },
    )
  }

  return (
    <>
      <PageHeader title="Open a case">One case per wallet. The trace follows the money from it to the nearest exchange, and says so when it cannot name one.</PageHeader>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,600px)_minmax(0,1fr)]">
        <form aria-label="Open a case" onSubmit={submit} noValidate className="rounded-md border border-rule bg-surface">
          <Group title="The wallet">
            <Field
              label="Wallet address"
              optional={false}
              value={address}
              onChange={(e) => {
                setAddress(e.target.value)
                openCase.reset()
              }}
              placeholder="Tron (T…), EVM (0x…) or Bitcoin (1…, 3…, bc1…)"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              error={addressError}
              hint="The chain is read from the address. Tron, Bitcoin, Ethereum, Polygon, Arbitrum, Base and Optimism wallets can be traced."
              className="pr-28 font-mono"
            >
              <span className="absolute right-2 flex items-center">
                {(seen.state === 'typing' || seen.state === 'invalid') && seen.guess && <ChainBadge chain={seen.guess} tentative />}
                {seen.state === 'valid' && !isEvm && <ChainBadge chain={seen.chain} />}
                {isEvm && (
                  <select
                    aria-label="Chain"
                    value={evmChain}
                    onChange={(e) => setEvmChain(e.target.value as Chain)}
                    className="h-6 rounded-sm border border-rule-strong bg-surface px-1 font-mono text-xs font-medium text-fg"
                  >
                    {EVM_TRACEABLE.map((c) => (
                      <option key={c} value={c}>
                        {CHAINS[c].name}
                      </option>
                    ))}
                  </select>
                )}
              </span>
            </Field>
          </Group>

          <Group title="The complaint">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Case reference" value={caseRef} onChange={(e) => setCaseRef(e.target.value)} placeholder="CC/2026/118" hint="Your station’s own reference." />
              <Field
                label="Complaint number"
                value={complaint}
                onChange={(e) => setComplaint(e.target.value)}
                inputMode="numeric"
                className="font-mono"
                hint="The 1930 helpline or NCRP acknowledgement number."
              />
              <Field
                label="Amount lost"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                inputMode="decimal"
                placeholder="40,50,000"
                className="pl-7 font-mono"
                error={amountError}
                hint="In rupees, as the complainant reported it."
              >
                <span aria-hidden className="pointer-events-none absolute left-3 text-sm text-muted">
                  ₹
                </span>
              </Field>
              <Field
                label="Date of the incident"
                type="date"
                value={date}
                max={today()}
                onChange={(e) => setDate(e.target.value)}
                className="font-mono"
                error={dateError}
                hint="When given, the trace reads the wallet’s transfers from this day on."
              />
            </div>
          </Group>

          <Group title="The trace">
            <div className="flex flex-col gap-1.5">
              <span className="text-sm font-medium text-fg">How many hops to follow the money</span>
              <HopLimit value={hops} onChange={setHops} name="max-hops" />
              <p className="text-xs text-muted">
                Three is usual. Each further hop reads more wallets and takes longer; a branch always ends at the first labelled wallet.
              </p>
            </div>
            <label className="flex items-start gap-2 text-sm text-fg">
              <input type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--fg)]" />
              <span>
                Trace again if this wallet already has a case
                <span className="block text-xs text-muted">Otherwise its stored result opens as it was last traced.</span>
              </span>
            </label>
          </Group>

          <div className="flex flex-wrap items-center gap-3 border-t border-rule bg-sunk px-5 py-4">
            <Button type="submit" variant="primary" disabled={!ready} icon={<CornerDownLeft size={14} aria-hidden />}>
              {openCase.isPending ? 'Opening…' : 'Trace wallet'}
            </Button>
            {openCase.isError && (
              <p role="alert" className="min-w-0 flex-1 text-sm font-medium text-seal-text">
                {openCase.error instanceof ApiError ? openCase.error.detail : 'The case could not be opened. Try again.'}
              </p>
            )}
          </div>
        </form>

        <DemoCases
          picked={seen.state === 'valid' ? seen.normalized : ''}
          onPick={(c) => {
            setAddress(c.address)
            if (CHAINS[c.chain].family === 'evm') setEvmChain(c.chain)
            openCase.reset()
          }}
        />
      </div>
    </>
  )
}
