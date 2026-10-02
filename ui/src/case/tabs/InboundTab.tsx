import type { CaseDetail, GraphEdge } from '../../api/models'
import { AddressChip } from '../../components/AddressChip'
import { Amount } from '../../components/Amount'
import { DataTable, type Column } from '../../components/DataTable'
import { EmptyState } from '../../components/EmptyState'
import { TierTag } from '../../components/TierTag'
import { traced } from '../../lib/caseGraph'
import { formatDate } from '../../lib/format'
import { isInbound } from '../rules'

interface Funder {
  address: string
  transfers: GraphEdge[]
  total: number
  first: string
  last: string
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Who paid the wallet the case is about: one hop back. An exchange among them can be asked
 *  which account withdrew to it; it is never part of where the money went. */
export function InboundTab({ c, onSelect }: { c: CaseDetail; onSelect: (address: string) => void }) {
  const inbound = c.graph.edges.filter((e) => e.direction === 'inbound').sort((a, b) => a.block_time.localeCompare(b.block_time))
  if (inbound.length === 0)
    return (
      <EmptyState title="No inbound transfer was read">
        The trace reads one hop back from the wallet, in the asset it followed. Nothing came in on that asset in the period traced.
      </EmptyState>
    )

  const byWallet = new Map<string, Funder>()
  for (const e of inbound.filter((x) => x.target === c.address)) {
    const f = byWallet.get(e.source) ?? { address: e.source, transfers: [], total: 0, first: e.block_time, last: e.block_time }
    f.transfers.push(e)
    f.total += traced(e)
    f.last = e.block_time
    byWallet.set(e.source, f)
  }
  const funders = [...byWallet.values()]
  const nodes = new Map(c.graph.nodes.map((n) => [n.id, n]))
  const asset = c.asset ?? inbound[0].asset
  const exchanges = c.candidates.filter(isInbound)
  const received = c.total_received ?? funders.reduce((sum, f) => sum + f.total, 0)

  const columns: Column<Funder>[] = [
    {
      key: 'wallet',
      header: 'Wallet',
      cell: (f) => (
        <AddressChip
          address={f.address}
          chain={c.chain}
          entity={nodes.get(f.address)?.label?.entity}
          tier={nodes.get(f.address)?.label?.tier}
          onSelect={() => onSelect(f.address)}
        />
      ),
    },
    { key: 'label', header: 'Label', cell: (f) => <TierTag tier={nodes.get(f.address)?.label?.tier ?? null} size="sm" /> },
    {
      key: 'n',
      header: 'Transfers',
      align: 'right',
      sortValue: (f) => f.transfers.length,
      cell: (f) => <span className="tabular font-mono text-sm">{f.transfers.length}</span>,
    },
    { key: 'total', header: 'Paid in', align: 'right', sortValue: (f) => f.total, cell: (f) => <Amount value={f.total} asset={asset} /> },
    {
      key: 'when',
      header: 'When',
      align: 'right',
      sortValue: (f) => f.first,
      cell: (f) => (
        <span className="tabular whitespace-nowrap font-mono text-xs text-muted">
          {formatDate(f.first)}
          {formatDate(f.last) !== formatDate(f.first) && ` to ${formatDate(f.last)}`}
        </span>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-fg">
        The wallet received <Amount value={received} asset={asset} /> in {plural(inbound.filter((e) => e.target === c.address).length, 'transfer')} from{' '}
        {plural(funders.length, 'wallet')}
      </p>

      {exchanges.length > 0 && (
        <section aria-label="Exchanges that funded the wallet" className="flex flex-col gap-3">
          <h3 className="eyebrow">Exchanges that funded the wallet</h3>
          <ul className="flex flex-col gap-3">
            {exchanges.map((x) => (
              <li key={x.vasp + x.deposit_address} className="flex flex-col gap-1.5 rounded border border-rule px-3 py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="display text-base text-fg">{x.vasp}</span>
                  <TierTag tier={x.label_tier} size="sm" />
                  <AddressChip address={x.deposit_address} chain={c.chain} onSelect={() => onSelect(x.deposit_address)} />
                </div>
                {x.evidence.map((e, i) => (
                  <p key={i} className="text-sm text-fg [overflow-wrap:anywhere]">
                    {e.text}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}

      <DataTable
        caption="Wallets that paid the suspect wallet"
        columns={columns}
        rows={funders}
        rowKey={(f) => f.address}
        initialSort={{ key: 'total', dir: 'desc' }}
        onRowOpen={(f) => onSelect(f.address)}
      />
    </div>
  )
}
