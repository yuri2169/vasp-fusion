import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import type { CaseDetail, EvidenceItem, GraphEdge, GraphNode, LabelOut } from '../api/models'
import { useOpenCase } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { Amount } from '../components/Amount'
import { Button } from '../components/Button'
import { EvidenceList } from '../components/EvidenceList'
import { TierTag } from '../components/TierTag'
import { useToast } from '../components/Toast'
import { TxHash } from '../components/TxHash'
import { TypologyFlag } from '../components/TypologyFlag'
import { ledgerOf, traced } from '../lib/caseGraph'
import { CHAINS } from '../lib/chains'
import { cx } from '../lib/cx'
import { formatConfidence, formatConfidenceRange, formatDateTime } from '../lib/format'
import { ROLE_NAMES } from './caseText'
import { Section } from './parts'

const KIND_NAMES: Record<LabelOut['kind'], string | null> = {
  deposit: 'deposit address',
  hot: 'hot wallet',
  cold: 'cold wallet',
  reserve: 'reserve wallet',
  unknown: null,
}

const LISTED = 5
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** Where the wallet stands relative to the one the case is about. */
function distance(c: CaseDetail, node: GraphNode): string {
  if (node.id === c.address) return 'The wallet this case is about'
  const receives = c.graph.edges.some((e) => e.target === node.id && e.direction !== 'inbound')
  if (!receives) return node.hop <= 1 ? 'Paid the suspect wallet directly' : `Funded the suspect wallet, ${plural(node.hop, 'hop')} back`
  return `${plural(node.hop, 'hop')} from the suspect wallet`
}

/** The label on a wallet: who, how it is known, and (for our own derived labels) what the rules and the model saw. */
function LabelBlock({ label, chain }: { label: LabelOut; chain: CaseDetail['chain'] }) {
  const kind = KIND_NAMES[label.kind]
  const scored = label.confidence_low != null && label.confidence_high != null
  const reasons: EvidenceItem[] = (label.model?.reasons ?? []).map((r) => ({ kind: 'model', text: r.text, weight: r.weight, tx_hashes: [], tier: null }))
  return (
    <Section title="Label">
      <div className="flex flex-wrap items-center gap-2">
        <span className="display text-lg text-fg">{label.entity}</span>
        <TierTag tier={label.tier} size="sm" />
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {kind && (
          <>
            <dt className="text-muted">Kind</dt>
            <dd className="text-fg">{kind}</dd>
          </>
        )}
        {label.label && (
          <>
            <dt className="text-muted">Tag</dt>
            <dd className="text-fg [overflow-wrap:anywhere]">“{label.label}”</dd>
          </>
        )}
        <dt className="text-muted">Source</dt>
        <dd className="text-fg [overflow-wrap:anywhere]">
          {label.source_url ? (
            <a href={label.source_url} target="_blank" rel="noopener noreferrer" className="underline decoration-rule-strong underline-offset-2 hover:decoration-fg">
              {label.source}
            </a>
          ) : (
            label.source
          )}
        </dd>
        {label.confidence != null && (
          <>
            <dt className="text-muted">Label</dt>
            <dd className="tabular font-mono text-fg">
              {scored
                ? `confidence ${formatConfidence(label.confidence)}, ${formatConfidenceRange(label.confidence_low!, label.confidence_high!)}`
                : `rule confidence ${formatConfidence(label.confidence)}`}
            </dd>
          </>
        )}
      </dl>
      {label.evidence && <p className="text-sm text-fg [overflow-wrap:anywhere]">{label.evidence}</p>}
      {label.model && (
        <div className="flex flex-col gap-1 rounded border border-rule bg-sunk px-3 py-2.5">
          <p className="text-sm text-fg">
            Deposit-address model: {formatConfidence(label.model.p)} that an address behaving like this is an exchange deposit address (
            {formatConfidenceRange(label.model.low, label.model.high)}).
            {label.model.basis === 'rule' && ' The label keeps the discovery rules’ confidence: the model’s value would not raise it.'}
          </p>
          <EvidenceList items={reasons} chain={chain} />
        </div>
      )}
    </Section>
  )
}

function TransferRow({ c, edge, other, onSelect }: { c: CaseDetail; edge: GraphEdge; other: string; onSelect: (address: string) => void }) {
  const whole = traced(edge) === edge.amount
  const node = c.graph.nodes.find((n) => n.id === other)
  return (
    <li className="flex flex-col gap-1 border-t border-rule py-2 first:border-t-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <AddressChip
          address={other}
          chain={c.chain}
          entity={node?.label?.entity}
          tier={node?.label?.tier}
          role={other === c.address ? 'suspect' : undefined}
          actions="copy"
          onSelect={() => onSelect(other)}
        />
        <Amount value={traced(edge)} asset={edge.asset} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-x-3 text-xs text-muted">
        <span className="tabular font-mono">
          {formatDateTime(edge.block_time)}
          {!whole && ` · part of a transfer of ${edge.amount.toLocaleString('en-US')} ${edge.asset}`}
        </span>
        <TxHash hash={edge.tx_hash} chain={c.chain} />
      </div>
    </li>
  )
}

function Transfers({ c, title, edges, side, onSelect }: { c: CaseDetail; title: string; edges: GraphEdge[]; side: 'source' | 'target'; onSelect: (a: string) => void }) {
  if (edges.length === 0) return null
  return (
    <div>
      <p className="text-xs font-medium text-muted">{title}</p>
      <ul>
        {edges.slice(0, LISTED).map((e) => (
          <TransferRow key={e.id} c={c} edge={e} other={e[side]} onSelect={onSelect} />
        ))}
      </ul>
      {edges.length > LISTED && <p className="pt-1 text-xs text-muted">and {edges.length - LISTED} more, in the Transfers tab</p>}
    </div>
  )
}

/** One wallet of the case, opened from the graph, the Hop Rail or the Wallets tab: what it
 *  is, how it is labelled and why, and what moved through it on this trail. */
export function WalletPanel({
  c,
  id,
  onSelect,
  onClose,
  className,
}: {
  c: CaseDetail
  /** An address, or `cluster:<exchange>` for the grouped wallets of one exchange. */
  id: string
  onSelect: (address: string) => void
  onClose: () => void
  className?: string
}) {
  const navigate = useNavigate()
  const openCase = useOpenCase()
  const { show } = useToast()

  const frame = cx('flex flex-col gap-5 rounded-md border border-rule-strong bg-surface p-5', className)
  const back = (
    <Button size="sm" variant="ghost" icon={<ArrowLeft size={13} aria-hidden />} onClick={onClose} className="-ml-2 self-start">
      Back to the answer
    </Button>
  )

  // --- the wallets of one exchange, grouped ---------------------------------
  if (id.startsWith('cluster:')) {
    const name = id.slice('cluster:'.length)
    const members = c.graph.nodes.filter((n) => n.cluster === name && n.id !== c.address)
    return (
      <section aria-labelledby="wallet-title" className={frame}>
        {back}
        <div className="flex flex-col gap-1">
          <p className="eyebrow">Exchange</p>
          <h2 id="wallet-title" className="display text-lg text-fg">
            {name}
          </h2>
          <p className="text-sm text-muted">{plural(members.length, 'wallet')} of this exchange are in the case</p>
        </div>
        <ul className="flex flex-col gap-3">
          {members.map((n) => (
            <li key={n.id} className="flex flex-col gap-1">
              <AddressChip address={n.id} chain={c.chain} entity={n.label?.entity} tier={n.label?.tier} onSelect={() => onSelect(n.id)} className="self-start" />
              <span className="text-xs text-muted">
                {ROLE_NAMES[n.role]} · {distance(c, n)}
              </span>
            </li>
          ))}
        </ul>
      </section>
    )
  }

  const node = c.graph.nodes.find((n) => n.id === id)
  if (!node)
    return (
      <section aria-labelledby="wallet-title" className={frame}>
        {back}
        <h2 id="wallet-title" className="display text-lg text-fg">
          Wallet
        </h2>
        <p className="text-sm text-fg">This wallet is not part of this case.</p>
      </section>
    )

  const ledger = ledgerOf(c, node.id)
  const patterns = c.typology_flags.filter((f) => f.wallet === node.id)
  const isSuspect = node.id === c.address
  const asset = c.asset ?? c.graph.edges[0]?.asset ?? ''

  const trace = () =>
    openCase.mutate(
      { address: node.id, chain: c.chain },
      {
        onSuccess: (opened) => navigate(`/cases/${encodeURIComponent(opened.id)}`, { state: { watched: true } }),
        onError: (error) =>
          show({ kind: 'error', title: 'The case could not be opened', detail: error instanceof ApiError ? error.detail : 'Try again.' }),
      },
    )

  return (
    <section aria-labelledby="wallet-title" className={frame}>
      {back}
      <div className="flex flex-col gap-2">
        <p className="eyebrow">Wallet · {CHAINS[c.chain].name}</p>
        <h2 id="wallet-title" className="display text-lg text-fg">
          {ROLE_NAMES[node.role]}
        </h2>
        <AddressChip address={node.id} chain={c.chain} full className="h-auto self-start py-1" />
        <p className="text-sm text-muted">{distance(c, node)}</p>
      </div>

      {node.label ? (
        <LabelBlock label={node.label} chain={c.chain} />
      ) : (
        <Section title="Label">
          <p className="text-sm text-fg">No label in any source.</p>
        </Section>
      )}

      {(ledger.incoming.length > 0 || ledger.outgoing.length > 0) && (
        <Section title="On this trail">
          <div className="flex flex-col gap-0.5 text-sm text-fg">
            {ledger.incoming.length > 0 && (
              <p>
                Received <Amount value={ledger.received} asset={asset} /> in {plural(ledger.incoming.length, 'transfer')}
              </p>
            )}
            {ledger.outgoing.length > 0 && (
              <p>
                {isSuspect ? 'Sent' : 'Passed on'} <Amount value={ledger.sent} asset={asset} /> in {plural(ledger.outgoing.length, 'transfer')}
              </p>
            )}
          </div>
          <Transfers c={c} title="In, from" edges={ledger.incoming} side="source" onSelect={onSelect} />
          <Transfers c={c} title="Out, to" edges={ledger.outgoing} side="target" onSelect={onSelect} />
        </Section>
      )}

      {patterns.length > 0 && (
        <Section title="Patterns on this wallet">
          <ul className="flex flex-col gap-2">
            {patterns.map((flag, i) => (
              <li key={flag.code + i}>
                <TypologyFlag flag={flag} />
              </li>
            ))}
          </ul>
        </Section>
      )}

      {!isSuspect && (
        <Button onClick={trace} disabled={openCase.isPending} className="self-start">
          {openCase.isPending ? 'Opening…' : 'Open a case for this wallet'}
        </Button>
      )}
    </section>
  )
}
