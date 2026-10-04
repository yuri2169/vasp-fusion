import type { CaseDetail, GraphEdge, GraphNode } from '../../api/models'
import { RISK_ORDER, RiskTag } from '../../components/RiskTag'
import { AddressChip } from '../../components/AddressChip'
import { Amount } from '../../components/Amount'
import { DataTable, type Column } from '../../components/DataTable'
import { TxHash } from '../../components/TxHash'
import { traced } from '../../lib/caseGraph'
import { formatAmount, formatDateTime } from '../../lib/format'

/** Every transfer of the case, as a table of record: sortable, with the whole hash one click away. */
export function TransfersTab({ c, onSelect }: { c: CaseDetail; onSelect: (address: string) => void }) {
  const nodes = new Map<string, GraphNode>(c.graph.nodes.map((n) => [n.id, n]))
  // A transfer not listed in risk.flows carries no indicator: it is Low.
  const flows = new Map((c.risk?.flows ?? []).map((f) => [f.edge_id, f]))
  const chip = (address: string) => (
    <AddressChip
      address={address}
      chain={c.chain}
      entity={nodes.get(address)?.label?.entity}
      tier={nodes.get(address)?.label?.tier}
      role={address === c.address ? 'suspect' : undefined}
      actions="copy"
      onSelect={() => onSelect(address)}
    />
  )

  const columns: Column<GraphEdge>[] = [
    {
      key: 'time',
      header: 'Time',
      sortValue: (e) => e.block_time,
      cell: (e) => <span className="tabular whitespace-nowrap font-mono text-sm text-fg">{formatDateTime(e.block_time)}</span>,
    },
    { key: 'dir', header: 'Way', sortValue: (e) => e.direction, cell: (e) => <span className="text-base">{e.direction === 'inbound' ? 'In' : 'Out'}</span> },
    { key: 'from', header: 'From', cell: (e) => chip(e.source) },
    { key: 'to', header: 'To', cell: (e) => chip(e.target) },
    {
      key: 'amount',
      header: 'Traced amount',
      align: 'right',
      sortValue: (e) => traced(e),
      cell: (e) => (
        <span className="flex flex-col items-end">
          <Amount value={traced(e)} asset={e.asset} usd={e.amount_usd != null && traced(e) === e.amount ? e.amount_usd : null} />
          {traced(e) !== e.amount && <span className="tabular font-mono text-sm text-muted">of {formatAmount(e.amount, e.asset)}</span>}
        </span>
      ),
    },
    { key: 'tx', header: 'Transaction', cell: (e) => <TxHash hash={e.tx_hash} chain={c.chain} /> },
    ...(c.risk
      ? [
          {
            key: 'risk',
            header: 'Flow risk',
            sortValue: (e: GraphEdge) => RISK_ORDER.indexOf(flows.get(e.id)?.risk_class ?? 'low'),
            cell: (e: GraphEdge) => {
              const flow = flows.get(e.id)
              return (
                <span className="flex flex-col items-start gap-0.5">
                  <RiskTag risk={flow?.risk_class ?? 'low'} kind="" />
                  {flow && <span className="max-w-[26ch] text-sm text-muted">{flow.reasons.join('; ')}</span>}
                </span>
              )
            },
          } satisfies Column<GraphEdge>,
        ]
      : []),
  ]

  return (
    <DataTable
      caption="Transfers"
      columns={columns}
      rows={c.graph.edges}
      rowKey={(e) => e.id}
      initialSort={{ key: 'time', dir: 'asc' }}
      empty="No transfers were read for this wallet."
      maxHeight={520}
    />
  )
}
