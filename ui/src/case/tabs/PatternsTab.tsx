import type { CaseDetail, TypologyFlag as Flag } from '../../api/models'
import { AddressChip } from '../../components/AddressChip'
import { EmptyState } from '../../components/EmptyState'
import { TxHash } from '../../components/TxHash'
import { TypologyFlag } from '../../components/TypologyFlag'
import { isLead } from '../rules'

const LISTED = 6

function FlagRow({ c, flag, onSelect }: { c: CaseDetail; flag: Flag; onSelect: (address: string) => void }) {
  const node = c.graph.nodes.find((n) => n.id === flag.wallet)
  return (
    <li className="flex flex-col gap-2">
      <TypologyFlag flag={flag} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 pl-3">
        {node && (
          <AddressChip
            address={flag.wallet}
            chain={c.chain}
            entity={node.label?.entity}
            tier={node.label?.tier}
            role={flag.wallet === c.address ? 'suspect' : undefined}
            actions="copy"
            onSelect={() => onSelect(flag.wallet)}
          />
        )}
        {flag.tx_hashes.slice(0, LISTED).map((hash) => (
          <TxHash key={hash} hash={hash} chain={c.chain} />
        ))}
        {flag.tx_hashes.length > LISTED && <span className="text-xs text-muted">and {flag.tx_hashes.length - LISTED} more</span>}
      </div>
    </li>
  )
}

/** What the trace saw in how the money moved. None of it decides the outcome, except money
 *  at a sanctioned address or a mixer. Leads are kept apart: they are something to look into. */
export function PatternsTab({ c, onSelect }: { c: CaseDetail; onSelect: (address: string) => void }) {
  const patterns = c.typology_flags.filter((f) => !isLead(f))
  const leads = c.typology_flags.filter(isLead)
  if (patterns.length === 0 && leads.length === 0)
    return (
      <EmptyState title="No pattern was seen in the traced funds">
        The trace looks for peel chains, rapid forwarding, fan-out and fan-in, round amounts, bridges, mixers and sanctioned addresses.
      </EmptyState>
    )

  return (
    <div className="flex flex-col gap-6">
      {patterns.length > 0 && (
        <section aria-label="Patterns in the traced funds" className="flex flex-col gap-3">
          <h3 className="eyebrow">Patterns in the traced funds</h3>
          <ul className="flex max-w-[860px] flex-col gap-4">
            {patterns.map((flag, i) => (
              <FlagRow key={flag.code + flag.wallet + i} c={c} flag={flag} onSelect={onSelect} />
            ))}
          </ul>
        </section>
      )}
      {leads.length > 0 && (
        <section aria-label="Leads to check, in full" className="flex flex-col gap-3">
          <h3 className="eyebrow">Leads to check</h3>
          <p className="max-w-prose text-sm text-muted">
            A lead is an unlabelled wallet that behaves like an exchange deposit address. It never changes the answer of the case.
          </p>
          <ul className="flex max-w-[860px] flex-col gap-4">
            {leads.map((flag, i) => (
              <FlagRow key={flag.wallet + i} c={c} flag={flag} onSelect={onSelect} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
