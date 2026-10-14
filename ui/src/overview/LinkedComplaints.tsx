import { Link } from 'react-router'
import type { SharedWallet } from '../api/models'
import { AddressChip } from '../components/AddressChip'
import { cx } from '../lib/cx'
import { formatAmount } from '../lib/format'
import { chainName } from './words'

/** What a link does not establish (mirrors vaspfusion/campaigns.py, LIMIT). */
export const LINK_LIMIT =
  'A shared wallet is a lead, not proof of one operation: an unlabelled public contract or service can appear as one, so read a link with its amounts. Exchange, bridge, mixer, swap-service and other labelled wallets are left out.'

const hopWords = (hop: number | null | undefined) => (hop == null ? '' : hop === 0 ? 'its own wallet' : `${hop} hop${hop === 1 ? '' : 's'} away`)

/** The case page's panel: the wallets this case's trace shares with other cases' traces. */
export function RelatedCasesPanel({ links, caseId }: { links: readonly SharedWallet[] | undefined; caseId: string }) {
  if (!links?.length) return null
  const others = new Set(links.flatMap((k) => k.cases.map((r) => r.case_id)).filter((id) => id !== caseId))
  return (
    <section aria-label="Related cases" data-related className="panel mt-4 p-4">
      <h2 className="eyebrow mb-1">Related cases</h2>
      <p className="mb-1 max-w-[100ch] text-base text-ink">
        This trace shares {links.length} wallet{links.length === 1 ? '' : 's'} with {others.size} other case{others.size === 1 ? '' : 's'}.
      </p>
      <p className="mb-3 max-w-[100ch] text-sm text-ink-soft">{LINK_LIMIT}</p>
      <SharedWallets links={links} current={caseId} />
    </section>
  )
}

/** Wallets the traces of different suspect wallets share, each with the cases that reach it, how far, and how much
 *  arrived. `current` is the case on screen: its own row is marked and the others link to their case. */
export function SharedWallets({ links, current }: { links: readonly SharedWallet[]; current?: string }) {
  return (
    <ul className="flex flex-col divide-y divide-rule-soft">
      {links.map((k) => (
        <li key={`${k.chain}:${k.address}`} data-shared={k.address} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <AddressChip address={k.address} chain={k.chain as never} actions="copy" to={`/wallets/${k.chain}/${k.address}`} />
            <span className="text-sm text-ink-soft">
              {chainName(k.chain)} · reached by {k.suspects} different suspect wallets
            </span>
            {k.flags.map((f) => (
              <span
                key={f}
                className={cx(
                  'border px-1.5 text-2xs font-semibold',
                  f.startsWith('Frozen by') ? 'border-chain bg-chain-wash text-chain' : 'border-danger bg-danger-wash text-danger',
                )}
              >
                {f}
              </span>
            ))}
          </p>
          {k.busy && (
            <p className="max-w-[90ch] text-sm text-ink-soft">
              A wallet with a great many counterparties: most likely a service that many people pay, which links nobody by itself.
            </p>
          )}
          <table className="w-full max-w-[900px] text-sm">
            <thead className="sr-only">
              <tr>
                <th>Case</th>
                <th>Distance</th>
                <th>Amount that arrived</th>
              </tr>
            </thead>
            <tbody>
              {k.cases.map((r) => (
                <tr key={r.case_id} className={cx(r.case_id === current && 'font-semibold')}>
                  <td className="py-0.5 pr-4">
                    {r.case_id === current ? (
                      <span>This case</span>
                    ) : (
                      <Link to={`/cases/${encodeURIComponent(r.case_id)}`} className="underline decoration-rule-strong underline-offset-2 hover:decoration-current">
                        Case {r.case_ref ?? r.case_id}
                      </Link>
                    )}
                  </td>
                  <td className="py-0.5 pr-4 text-ink-soft">{r.is_suspect ? 'is its suspect wallet' : hopWords(r.hop)}</td>
                  <td className="tabular py-0.5 text-right font-mono">
                    {r.is_suspect ? '' : r.asset ? formatAmount(r.amount, r.asset) : r.amount}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </li>
      ))}
    </ul>
  )
}
