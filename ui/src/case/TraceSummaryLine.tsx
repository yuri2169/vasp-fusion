import { useId, useState } from 'react'
import type { Chain, TraceSummary } from '../api/models'
import { AddressChip } from '../components/AddressChip'
import { count, plural } from '../overview/words'

export interface TraceSummaryLineProps {
  summary: TraceSummary
  chain: Chain
  /** The wallets that are on the graph: one of these can be shown there. */
  onGraph: ReadonlySet<string>
  selected: string | null
  onSelect: (id: string) => void
}

/** What the trace saw against what the graph draws, in one line: the picture is sparse on
 *  purpose, and this says by how much and why. Each reason opens the list of its wallets. */
export function TraceSummaryLine({ summary: s, chain, onGraph, selected, onSelect }: TraceSummaryLineProps) {
  const [open, setOpen] = useState<string | null>(null)
  const listId = useId()
  const shown = s.not_followed.find((r) => r.reason === open)

  return (
    <div className="border-b border-rule px-4 py-2 text-sm text-muted" data-testid="trace-summary">
      <p>
        Followed{' '}
        <strong className="tabular font-semibold text-fg">
          {count(s.transfers_followed)} of {count(s.transfers_seen)}
        </strong>{' '}
        {s.transfers_seen === 1 ? 'transfer' : 'transfers'} seen.{' '}
        {s.not_followed.length === 0 ? (
          'Every wallet the money reached was read.'
        ) : (
          <>
            <strong className="font-semibold text-fg">{plural(s.wallets_not_followed, 'wallet')} not followed:</strong>{' '}
            {s.not_followed.map((r, i) => (
              <span key={r.reason}>
                <button
                  type="button"
                  aria-expanded={open === r.reason}
                  aria-controls={listId}
                  onClick={() => setOpen(open === r.reason ? null : r.reason)}
                  className="rounded-sm text-fg underline decoration-rule-strong underline-offset-2 hover:decoration-fg"
                >
                  {r.text}
                </button>
                {i < s.not_followed.length - 1 ? ', ' : '.'}
              </span>
            ))}
          </>
        )}
      </p>
      <div id={listId}>
        {shown && (
          <div className="mt-2 border-l-2 border-rule pl-3">
            <p className="text-fg">
              {shown.text}
              {shown.reason === 'dust' || shown.reason === 'other_chain' ? '. No traced money reached them, so they are not on the graph.' : '. Choose one to show it on the graph.'}
            </p>
            <ul className="mt-1.5 flex max-h-40 flex-wrap gap-x-4 gap-y-1 overflow-y-auto">
              {shown.wallet_ids.map((id) => (
                <li key={id}>
                  <AddressChip address={id} chain={chain} actions="copy" selected={selected === id} onSelect={onGraph.has(id) ? () => onSelect(id) : undefined} />
                </li>
              ))}
            </ul>
            {shown.count > shown.wallet_ids.length && <p className="mt-1.5">and {count(shown.count - shown.wallet_ids.length)} more, not listed here.</p>}
          </div>
        )}
      </div>
    </div>
  )
}
