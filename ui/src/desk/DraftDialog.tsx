import { useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import type { Ask, VaspWallet } from '../api/models'
import { useCases, useDraftRequest, useMe, useVasp } from '../api/queries'
import { Button } from '../components/Button'
import { Dialog } from '../components/Dialog'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { formatUsd } from '../lib/format'
import { ASK_ORDER, ASK_WORDS } from './status'

const OFFICER_KEY = 'vaspfusion.officer'

const remembered = (): string => {
  try {
    return localStorage.getItem(OFFICER_KEY) ?? ''
  } catch {
    return ''
  }
}

interface CaseGroup {
  caseId: string
  wallets: VaspWallet[]
  usd: number | null
}

/** The wallets a request can list, grouped by the case they come from (a request is drafted by case). */
function groups(wallets: VaspWallet[]): CaseGroup[] {
  const by = new Map<string, VaspWallet[]>()
  for (const w of wallets) if (w.routable !== false && w.case_id) by.set(w.case_id, [...(by.get(w.case_id) ?? []), w])
  return [...by].map(([caseId, ws]) => ({
    caseId,
    wallets: ws,
    usd: ws.some((w) => w.amount_usd != null) ? ws.reduce((sum, w) => sum + (w.amount_usd ?? 0), 0) : null,
  }))
}

/** Draft one consolidated request to an exchange: which cases it covers, what it asks for,
 *  and the officer whose name goes under the signature line. The letter itself is written
 *  by the server; it opens as a draft for review. */
export function DraftDialog({ vasp, preselect, onClose }: { vasp: string; preselect?: string[]; onClose: () => void }) {
  const page = useVasp(vasp)
  const cases = useCases()
  const me = useMe()
  const draft = useDraftRequest()
  const navigate = useNavigate()
  const toast = useToast()
  const officerId = useId()

  const available = useMemo(() => groups(page.data?.wallets ?? []), [page.data])
  const refOf = (id: string) => cases.data?.items.find((c) => c.id === id)?.case_ref ?? id
  const name = page.data?.directory.name ?? vasp

  const [picked, setPicked] = useState<Set<string> | null>(null)
  const [asks, setAsks] = useState<Set<Ask>>(new Set(ASK_ORDER))
  const [officer, setOfficer] = useState<string | null>(null)

  // Until the officer touches them: the cases the link named (else all of them), and who is signed in.
  const chosen = picked ?? new Set(available.filter((g) => !preselect?.length || preselect.includes(g.caseId)).map((g) => g.caseId))
  const signedIn = me.data?.officer ? [me.data.officer.name, me.data.officer.post].filter(Boolean).join(', ') : ''
  const officerLine = officer ?? (signedIn || remembered())

  const toggle = <T,>(set: Set<T>, item: T) => {
    const next = new Set(set)
    if (next.has(item)) next.delete(item)
    else next.add(item)
    return next
  }

  const ready = chosen.size > 0 && asks.size > 0 && officerLine.trim() !== '' && !draft.isPending
  const submit = () => {
    if (!ready) return
    try {
      localStorage.setItem(OFFICER_KEY, officerLine.trim())
    } catch {
      /* private mode: the name is simply not remembered */
    }
    draft.mutate(
      { vasp: name, case_ids: available.filter((g) => chosen.has(g.caseId)).map((g) => g.caseId), asks: ASK_ORDER.filter((a) => asks.has(a)), officer: officerLine.trim() },
      {
        onSuccess: (made) => {
          toast.show({ kind: 'success', title: 'Request drafted', detail: `${made.reference} to ${made.vasp}. Review it before approving.` })
          navigate(`/requests/${encodeURIComponent(made.id)}`)
        },
      },
    )
  }

  const box = 'mt-0.5 h-4 w-4 shrink-0 accent-[var(--fg)]'

  return (
    <Dialog
      open
      onClose={onClose}
      title={`Draft request to ${name}`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!ready} onClick={submit}>
            {draft.isPending ? 'Drafting…' : 'Draft request'}
          </Button>
        </>
      }
    >
      {page.isPending ? (
        <div className="flex flex-col gap-2 py-2" aria-busy="true">
          <Skeleton width="60%" />
          <Skeleton width="80%" />
        </div>
      ) : page.isError ? (
        <p role="alert" className="text-seal-text">
          {page.error instanceof ApiError ? page.error.detail : 'The exchange could not be loaded. Try again.'}
        </p>
      ) : available.length === 0 ? (
        <p>
          No wallet of {name} can be put in a request. A request needs a wallet the funds reached, at or above the 0.60 naming bar, in a
          finished case.
        </p>
      ) : (
        <form
          className="flex flex-col gap-5"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <p className="text-muted">
            One letter covers every case chosen here. It opens as a draft: nothing is sent until it is approved and marked as sent.
          </p>

          <fieldset className="flex flex-col gap-2">
            <legend className="eyebrow mb-2">Cases to include</legend>
            {available.map((g) => (
              <label key={g.caseId} className="flex cursor-pointer items-start gap-2.5">
                <input type="checkbox" className={box} checked={chosen.has(g.caseId)} onChange={() => setPicked(toggle(chosen, g.caseId))} />
                <span className="min-w-0">
                  <span className="font-medium">{refOf(g.caseId)}</span>
                  <span className="tabular block font-mono text-xs text-muted">
                    {g.wallets.length} {g.wallets.length === 1 ? 'wallet' : 'wallets'}
                    {g.usd != null && ` · ${formatUsd(g.usd)}`}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>

          <fieldset className="flex flex-col gap-2">
            <legend className="eyebrow mb-2">Ask for</legend>
            {ASK_ORDER.map((ask) => (
              <label key={ask} className="flex cursor-pointer items-start gap-2.5">
                <input type="checkbox" className={box} checked={asks.has(ask)} onChange={() => setAsks(toggle(asks, ask))} />
                <span>
                  {ASK_WORDS[ask]}
                  {ask === 'freeze' && <span className="block text-xs text-muted">Adds Section 106 BNSS to the legal basis.</span>}
                </span>
              </label>
            ))}
          </fieldset>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={officerId} className="eyebrow">
              Investigating officer
            </label>
            <input
              id={officerId}
              value={officerLine}
              onChange={(e) => setOfficer(e.target.value)}
              placeholder="Rank, name, police station"
              autoComplete="off"
              className="h-9 rounded border border-rule-strong bg-surface px-2.5 text-sm text-fg placeholder:text-muted"
            />
            <span className="text-xs text-muted">Printed under the signature line. Latin letters only: the letter's PDF cannot print other scripts.</span>
          </div>

          {draft.isError && (
            <p role="alert" className="rounded border border-seal-text bg-seal-wash px-3 py-2 text-seal-text [overflow-wrap:anywhere]">
              {draft.error instanceof ApiError ? draft.error.detail : 'The request could not be drafted. Try again.'}
            </p>
          )}
        </form>
      )}
    </Dialog>
  )
}
