import type { CaseDetail, GraphNode } from '../../api/models'
import { AddressChip } from '../../components/AddressChip'
import { Amount } from '../../components/Amount'
import { DataTable, type Column } from '../../components/DataTable'
import { TierTag } from '../../components/TierTag'
import { ledgerOf } from '../../lib/caseGraph'
import { ROLE_NAMES } from '../caseText'

/** Every wallet in the graph, as rows: what the canvas shows, for a keyboard and a screen
 *  reader. Opening a row selects the wallet exactly as a click on its node does. */
export function WalletsTab({ c, selected, onSelect }: { c: CaseDetail; selected: string | null; onSelect: (address: string) => void }) {
  const asset = c.asset ?? c.graph.edges[0]?.asset ?? ''
  const funds = new Map(c.graph.nodes.map((n) => [n.id, ledgerOf(c, n.id)]))
  const isFunder = (n: GraphNode) => n.id !== c.address && !c.graph.edges.some((e) => e.target === n.id && e.direction !== 'inbound')
  const money = (value: number) => (value > 0 ? <Amount value={value} asset={asset} /> : <span className="text-muted">none</span>)

  const columns: Column<GraphNode>[] = [
    {
      key: 'wallet',
      header: 'Wallet',
      cell: (n) => (
        <AddressChip
          address={n.id}
          chain={c.chain}
          entity={n.label?.entity}
          tier={n.label?.tier}
          role={n.id === c.address ? 'suspect' : undefined}
          selected={selected === n.id}
          onSelect={() => onSelect(n.id)}
        />
      ),
    },
    { key: 'role', header: 'Role', sortValue: (n) => ROLE_NAMES[n.role], cell: (n) => <span className="text-base">{ROLE_NAMES[n.role]}</span> },
    { key: 'tier', header: 'Label', sortValue: (n) => n.label?.tier ?? null, cell: (n) => <TierTag tier={n.label?.tier ?? null} size="sm" /> },
    {
      key: 'hop',
      header: 'Hops',
      align: 'right',
      sortValue: (n) => (isFunder(n) ? -n.hop : n.hop),
      cell: (n) => <span className="tabular font-mono text-base">{n.id === c.address ? '0' : isFunder(n) ? `${n.hop} back` : n.hop}</span>,
    },
    { key: 'in', header: 'Received', align: 'right', sortValue: (n) => funds.get(n.id)!.received, cell: (n) => money(funds.get(n.id)!.received) },
    { key: 'out', header: 'Sent on', align: 'right', sortValue: (n) => funds.get(n.id)!.sent, cell: (n) => money(funds.get(n.id)!.sent) },
  ]

  return (
    <DataTable
      caption="Wallets"
      columns={columns}
      rows={c.graph.nodes}
      rowKey={(n) => n.id}
      initialSort={{ key: 'hop', dir: 'asc' }}
      onRowOpen={(n) => onSelect(n.id)}
      empty="No wallets were reached."
      maxHeight={520}
    />
  )
}
