import { Snowflake } from 'lucide-react'
import type { IssuerRequest } from '../api/models'
import { api } from '../api/api'
import { AddressChip } from '../components/AddressChip'
import { buttonClass } from '../components/Button'
import { Rupees } from '../components/Rupees'
import { formatAmount, formatDateTime } from '../lib/format'

const SHOWN = 10

/** A draft request to the issuer of USDT to freeze traced USDT at addresses outside any exchange. Offered beside
 *  the exchange request; a draft that this tool never sends. It names only what the issuer itself publishes about
 *  where to write. */
export function IssuerRequestPanel({ request, caseId, chain }: { request: IssuerRequest; caseId: string; chain: string }) {
  const d = request.draft
  if (!request.offered || !d) return null
  return (
    <section aria-label="Request to the issuer of USDT" data-issuer-request className="panel mt-4 p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="eyebrow mb-1 inline-flex items-center gap-1.5">
            <Snowflake size={13} aria-hidden className="text-chain" />
            Request to the issuer of USDT
          </h2>
          <p className="max-w-[100ch] text-base text-ink">{request.reason}</p>
        </div>
        <a href={api.issuerRequestPdfUrl(caseId)} target="_blank" rel="noopener noreferrer" className={buttonClass('secondary', 'sm')}>
          Open the draft (PDF)
        </a>
      </div>
      <p className="mb-3 max-w-[100ch] text-sm text-ink-soft">
        A draft for the officer: the legal provision and the officer’s details are left blank, and nothing is sent. {d.channel}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-base">
          <thead>
            <tr className="border-b border-ink text-left">
              <th className="colhead py-1.5 pr-3">Address</th>
              <th className="colhead py-1.5 pr-3">What happened there</th>
              <th className="colhead py-1.5 pr-3 text-right">USDT received</th>
              <th className="colhead py-1.5 pr-3 text-right">Left there</th>
              <th className="colhead py-1.5">First arrived</th>
            </tr>
          </thead>
          <tbody>
            {d.wallets.slice(0, SHOWN).map((w) => (
              <tr key={w.address} className="border-b border-rule-soft align-top">
                <td className="py-2 pr-3">
                  <AddressChip address={w.address} chain={(w.chain || chain) as never} head={6} tail={6} actions="copy" />
                  {w.label && <span className="mt-1 block text-sm text-ink-soft">{w.label}</span>}
                </td>
                <td className="py-2 pr-3 text-sm text-ink">
                  {w.role === 'held' ? 'Funds stopped here' : 'Passed the funds on'}, {w.hop} hop{w.hop === 1 ? '' : 's'} out
                  {w.busy && <span className="mt-0.5 block text-ink-soft">A wallet with a great many counterparties: probably a service. Check before asking.</span>}
                </td>
                <td className="tabular py-2 pr-3 text-right font-mono text-sm">{formatAmount(w.received, w.asset)}</td>
                <td className="tabular py-2 pr-3 text-right font-mono text-sm">
                  {formatAmount(w.held, w.asset)}
                  <Rupees usd={w.held} className="block text-muted" />
                </td>
                <td className="py-2 text-sm text-ink-soft">{formatDateTime(w.first_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d.wallets.length > SHOWN && (
        <p className="mt-2 text-sm text-ink-soft">
          The {SHOWN} that hold the most are shown; the draft lists all {d.wallets.length}.
        </p>
      )}
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-semibold text-ink">Before sending ({d.review_notes.length})</summary>
        <ul className="mt-1.5 flex flex-col gap-1">
          {d.review_notes.map((n) => (
            <li key={n} className="max-w-[100ch] text-sm text-ink [overflow-wrap:anywhere]">
              {n}
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}
