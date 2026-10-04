import { FileDown, Printer } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { API_MODE, api } from '../api/api'
import { ApiError } from '../api/client'
import type { RequestDetail } from '../api/models'
import { useRequest } from '../api/queries'
import { Button, buttonClass } from '../components/Button'
import { CopyButton } from '../components/CopyButton'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { LetterSheet } from '../desk/LetterSheet'
import { RequestActions } from '../desk/RequestActions'
import { RoutingSlip } from '../desk/RoutingSlip'
import { StatusTag } from '../desk/StatusTag'
import { isOverdue, standing } from '../desk/status'
import { formatDate, formatDateTime } from '../lib/format'

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="flex flex-col gap-2">
      <h2 className="eyebrow">{title}</h2>
      {children}
    </section>
  )
}

/** Where the request went once it was sent: what the gateway gave back, with the digest of what was handed over. */
function GatewayReceipt({ receipt }: { receipt: NonNullable<RequestDetail['receipt']> }) {
  const rows: [string, ReactNode][] = [
    ['Gateway', receipt.gateway],
    ['Receipt', receipt.receipt_id],
    ['Handed over', formatDateTime(receipt.submitted_at)],
    ['Where', receipt.location],
  ]
  return (
    <dl className="rounded border border-rule bg-surface px-3 py-2 text-xs">
      {rows.map(([name, value]) => (
        <div key={name} className="flex justify-between gap-3 py-0.5">
          <dt className="text-muted">{name}</dt>
          <dd className="min-w-0 break-all text-right font-mono text-fg">{value}</dd>
        </div>
      ))}
      <div className="mt-1 border-t border-rule pt-1.5">
        <dt className="flex items-center justify-between text-muted">
          SHA-256 of the data handed over
          <CopyButton value={receipt.payload_sha256} label="digest" />
        </dt>
        <dd className="break-all font-mono text-fg">{receipt.payload_sha256}</dd>
      </div>
      {receipt.gateway === 'mock-outbox' && (
        <p className="mt-1.5 border-t border-rule pt-1.5 text-muted">
          This installation is not connected to SAHYOG: the request was written to a local outbox, and nothing left this machine.
        </p>
      )}
    </dl>
  )
}

/** One request: the letter as it will be read, and beside it where it stands, what to do next,
 *  what to check, and how to put it on paper. */
export function RequestPage() {
  const { id = '' } = useParams()
  const request = useRequest(id)
  const r = request.data

  if (request.isError)
    return (
      <>
        <PageHeader eyebrow={<Link to="/requests">All requests</Link>} title="Request" />
        <ErrorState
          title="This request could not be loaded"
          detail={request.error instanceof ApiError ? (request.error.status === 404 ? `There is no request "${id}".` : request.error.detail) : 'Try again.'}
          onRetry={() => void request.refetch()}
        />
      </>
    )

  if (!r)
    return (
      <div className="flex flex-col gap-3" aria-busy="true">
        <Skeleton width="30%" />
        <Skeleton width="60%" />
        <Skeleton width="50%" />
      </div>
    )

  const notes = r.letter.review_notes ?? []
  const cases = r.letter.cases ?? []
  const overdue = isOverdue(r)

  return (
    <>
      <div className="print:hidden">
        <PageHeader
          eyebrow={
            <>
              <Link to="/requests">All requests</Link> · <span className="font-mono normal-case tracking-normal">{r.reference}</span>
            </>
          }
          title={
            <>
              Request to{' '}
              <Link to={`/vasps/${encodeURIComponent(r.vasp)}`} className="underline decoration-rule-strong underline-offset-4 hover:decoration-current">
                {r.vasp}
              </Link>
            </>
          }
          meta={
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <StatusTag status={r.status} />
              <span>
                {r.letter.wallets.length} {r.letter.wallets.length === 1 ? 'wallet' : 'wallets'} from{' '}
                {(cases.length > 0 ? cases.map((c) => ({ id: c.case_id, ref: c.case_ref ?? c.case_id })) : r.case_ids.map((cid) => ({ id: cid, ref: cid }))).map((c, i) => (
                  <span key={c.id}>
                    {i > 0 && ', '}
                    <Link to={`/cases/${encodeURIComponent(c.id)}`} className="underline decoration-rule-strong underline-offset-2 hover:text-fg">
                      {c.ref}
                    </Link>
                  </span>
                ))}
              </span>
              {r.due && (
                <span className={overdue ? 'font-medium text-seal-text' : undefined}>
                  · reply due {formatDate(r.due)}
                  {overdue && ', overdue'}
                </span>
              )}
            </span>
          }
        />
      </div>

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_320px] print:block">
        <aside aria-label="This request: next step, checks and history" className="flex flex-col gap-6 lg:sticky lg:top-[76px] lg:order-2 print:hidden">
          <Block title="Next step">
            <p className="text-sm text-fg">{standing(r)}</p>
            <RequestActions request={r} />
          </Block>

          {notes.length > 0 && (
            <Block title={r.status === 'drafted' ? 'Check before approving' : 'Notes for the reviewing officer'}>
              <ul className="flex flex-col gap-2 rounded border border-dashed border-rule-strong bg-surface px-3 py-2.5">
                {notes.map((note, i) => (
                  <li key={i} className="flex gap-2 text-xs text-fg">
                    <span aria-hidden className="select-none text-muted">
                      –
                    </span>
                    <span className="min-w-0 [overflow-wrap:anywhere]">{note}</span>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted">Not part of the request. A draft's printout carries them on a last sheet.</p>
            </Block>
          )}

          <Block title="Routing slip">
            <RoutingSlip history={r.status_history} status={r.status} layout="column" />
          </Block>

          {r.receipt && (
            <Block title="Gateway receipt">
              <GatewayReceipt receipt={r.receipt} />
            </Block>
          )}

          <Block title="On paper">
            <div className="flex flex-wrap gap-2">
              <Button icon={<Printer size={15} aria-hidden />} onClick={() => window.print()}>
                Print
              </Button>
              {API_MODE === 'live' && (
                <a href={api.requestPdfUrl(r.id)} target="_blank" rel="noreferrer" className={buttonClass('secondary')}>
                  <FileDown size={15} aria-hidden />
                  Open letter PDF
                </a>
              )}
            </div>
            <p className="text-xs text-muted">
              Prints on A4 with the reference and page number on every page. In the print dialog, switch off the browser's own headers and footers.
              {r.letter.watermark && ' A draft prints with its watermark.'}
              {API_MODE === 'live' && r.receipt && " The letter PDF is the very file that was handed to the gateway."}
            </p>
          </Block>
        </aside>

        <div className="min-w-0 lg:order-1">
          <LetterSheet letter={r.letter} />
        </div>
      </div>
    </>
  )
}
