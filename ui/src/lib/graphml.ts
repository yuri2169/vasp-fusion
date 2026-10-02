/** A case's fund-flow graph as GraphML, for Gephi, yEd, Maltego and the like: one node per
 *  wallet, one edge per transfer, addresses and hashes whole. */
import type { CaseDetail } from '../api/models'

type Value = string | number | boolean | null | undefined
type Kind = 'string' | 'double' | 'int' | 'boolean'

const KEYS: Record<'graph' | 'node' | 'edge', Record<string, Kind>> = {
  graph: {
    case_id: 'string',
    case_ref: 'string',
    wallet: 'string',
    chain: 'string',
    outcome: 'string',
    top_vasp: 'string',
    confidence: 'double',
    asset: 'string',
    findings_sha256: 'string',
  },
  node: {
    chain: 'string',
    role: 'string',
    hop: 'int',
    entity: 'string',
    category: 'string',
    kind: 'string',
    tier: 'string',
    label_source: 'string',
    cluster: 'string',
    is_hub: 'boolean',
  },
  edge: {
    tx_hash: 'string',
    asset: 'string',
    amount: 'double',
    traced_amount: 'double',
    amount_usd: 'double',
    block_time: 'string',
    direction: 'string',
  },
}

const escape = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;')

/** One <data> per value that is set; a missing value is left out, not written as empty. */
const data = (values: Record<string, Value>, indent: string) =>
  Object.entries(values)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([key, v]) => `${indent}<data key="${key}">${escape(String(v))}</data>`)

export function toGraphML(c: CaseDetail): string {
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">']
  for (const [domain, keys] of Object.entries(KEYS))
    for (const [name, kind] of Object.entries(keys))
      lines.push(`  <key id="${name}" for="${domain}" attr.name="${name}" attr.type="${kind}"/>`)

  lines.push(`  <graph id="${escape(c.id)}" edgedefault="directed">`)
  lines.push(
    ...data(
      {
        case_id: c.id,
        case_ref: c.case_ref,
        wallet: c.address,
        chain: c.chain,
        outcome: c.outcome,
        top_vasp: c.top_vasp,
        confidence: c.confidence,
        asset: c.asset,
        findings_sha256: c.provenance.findings_sha256,
      },
      '    ',
    ),
  )
  for (const n of c.graph.nodes) {
    lines.push(`    <node id="${escape(n.id)}">`)
    lines.push(
      ...data(
        {
          chain: n.chain,
          role: n.role,
          hop: n.hop,
          entity: n.label?.entity,
          category: n.label?.category,
          kind: n.label?.kind,
          tier: n.label?.tier,
          label_source: n.label?.source,
          cluster: n.cluster,
          is_hub: n.is_hub,
        },
        '      ',
      ),
    )
    lines.push('    </node>')
  }
  for (const e of c.graph.edges) {
    lines.push(`    <edge id="${escape(e.id)}" source="${escape(e.source)}" target="${escape(e.target)}">`)
    lines.push(
      ...data(
        {
          tx_hash: e.tx_hash,
          asset: e.asset,
          amount: e.amount,
          traced_amount: e.traced_amount,
          amount_usd: e.amount_usd,
          block_time: e.block_time,
          direction: e.direction,
        },
        '      ',
      ),
    )
    lines.push('    </edge>')
  }
  lines.push('  </graph>', '</graphml>', '')
  return lines.join('\n')
}
