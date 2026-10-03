import { useQuery } from '@tanstack/react-query'
import { FolderOpen, RotateCcw } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { api } from '../api/api'
import type { CaseDetail, Chain, FundsSlice, GraphNode, LabelOut, Severity, Tier, TypologyCode } from '../api/models'
import { AddressChip } from '../components/AddressChip'
import { Amount } from '../components/Amount'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { DataTable, type Column } from '../components/DataTable'
import { Dialog } from '../components/Dialog'
import { DualMeter } from '../components/DualMeter'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { EvidenceList } from '../components/EvidenceList'
import { FundsBar } from '../components/FundsBar'
import { HopRail } from '../components/HopRail'
import { RoutingSlip } from '../desk/RoutingSlip'
import { StatusTag } from '../desk/StatusTag'
import { STATUS_ORDER } from '../desk/status'
import { OutcomeStamp } from '../components/OutcomeStamp'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { Tabs } from '../components/Tabs'
import { TierTag } from '../components/TierTag'
import { useToast } from '../components/Toast'
import { TxHash } from '../components/TxHash'
import { TypologyFlag } from '../components/TypologyFlag'
import { CHAINS } from '../lib/chains'
import { formatInr } from '../lib/format'

/** /kit: every component in every state, on one page, in whichever theme is on.
 *  It is the reference for the later UI phases and the page the screenshots are taken of
 *  (`npm run screenshots`; `?theme=dark` forces a theme).
 *
 *  Nothing here is invented: the cases and labels are the B1 fixtures, read through the API
 *  client like any other screen, and the lone addresses are the real demo wallets. */

const DEMO_CASES = ['demo-tron-okx', 'demo-eth-abstain', 'demo-tron-sanctioned'] as const

// Real wallets from demo/cases.json (PROGRESS.md, B3 and B5). Nothing about them is alleged.
const HERO_TRON = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c'
const DEMO_BTC = 'bc1qw75rzzczmu2ulmjnrat3kn8h2rrrlr6wt7q3x6'

// Where the money of three real demo wallets ended up (`where_funds_went` of tron-coindcx,
// tron-ofac and eth-bridge as traced on 2 Oct 2026; PROGRESS.md, B3 and B7). The B1 fixtures
// were recorded before that field existed, so the kit carries these figures itself.
const FUNDS: { asset: string; total: number; named?: string; slices: FundsSlice[] }[] = [
  {
    asset: 'USDT',
    total: 2652.22,
    named: 'CoinDCX',
    slices: [
      { kind: 'vasp', name: 'CoinDCX', share: 0.5769, amount: 1530 },
      { kind: 'hub', name: null, share: 0.4231, amount: 1122.22 },
    ],
  },
  {
    asset: 'USDT',
    total: 101078.339672,
    slices: [
      { kind: 'sanctioned', name: 'OFAC SDN', share: 0.9894, amount: 100008 },
      { kind: 'beyond_hop_limit', name: null, share: 0.0104, amount: 1052 },
      { kind: 'not_followed', name: null, share: 0.0002, amount: 18.339672 },
    ],
  },
  {
    asset: 'USDT',
    total: 13705.0531,
    slices: [
      { kind: 'bridge', name: 'Across Protocol', share: 0.602, amount: 8250 },
      { kind: 'other_label', name: 'Uniswap V4', share: 0.2533, amount: 3471.123121 },
      { kind: 'not_followed', name: null, share: 0.0429, amount: 587.37486 },
      { kind: 'hub', name: null, share: 0.0414, amount: 567.877379 },
      { kind: 'bridge', name: 'Optimism', share: 0.0365, amount: 500 },
      { kind: 'beyond_hop_limit', name: null, share: 0.0233, amount: 320 },
      { kind: 'returned', name: null, share: 0.0006, amount: 8.67774 },
    ],
  },
]

const KIT_TABS = [
  { id: 'timeline', label: 'Timeline' },
  { id: 'transfers', label: 'Transfers', count: 7 },
  { id: 'wallets', label: 'Wallets', count: 8 },
  { id: 'audit', label: 'Audit' },
]

// Every pattern code with the severity the contract gives it (docs/api_contract.md, B7 and B5).
const PATTERNS: [TypologyCode, Severity][] = [
  ['sanctioned_contact', 'high'],
  ['mixer_contact', 'high'],
  ['bridge_hop', 'warn'],
  ['peel_chain', 'warn'],
  ['rapid_forwarding', 'warn'],
  ['coinjoin_shape', 'warn'],
  ['fan_out', 'info'],
  ['fan_in', 'info'],
  ['round_amounts', 'info'],
  ['deposit_like', 'info'],
]

const BRAND: [string, string, string][] = [
  ['--ink', '#2B1622', 'Nav rail, headings'],
  ['--paper', '#F5F4F8', 'Page background'],
  ['--saffron', '#E8772E', 'The attributed exchange, the primary action'],
  ['--verified', '#1F7A74', 'Published or explorer-tagged evidence'],
  ['--seal', '#B3261E', 'Sanctioned, mixer, freeze'],
  ['--slate', '#5B5566', 'Secondary text, derived evidence'],
]

const ROLES: [string, string][] = [
  ['--bg', 'Page'],
  ['--surface', 'Cards, tables'],
  ['--surface-sunk', 'Wells, table header'],
  ['--rule', 'Hairlines'],
  ['--rule-strong', 'Control borders'],
  ['--fg', 'Text'],
  ['--fg-muted', 'Secondary text'],
  ['--saffron-text', 'Saffron as text'],
  ['--verified-text', 'Teal as text'],
  ['--seal-text', 'Red as text'],
  ['--saffron-wash', 'Saffron tint'],
  ['--verified-wash', 'Teal tint'],
  ['--seal-wash', 'Red tint'],
  ['--slate-wash', 'Slate tint'],
]

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  const id = title.toLowerCase().replace(/[^a-z]+/g, '-')
  return (
    <section aria-labelledby={id} className="border-t border-rule py-8">
      <div className="mb-5 grid gap-x-8 gap-y-1 lg:grid-cols-[220px_1fr]">
        <h2 id={id} className="display text-lg">
          {title}
        </h2>
        {note && <p className="max-w-prose text-sm text-muted">{note}</p>}
      </div>
      <div className="flex flex-col gap-6">{children}</div>
    </section>
  )
}

/** One specimen: its name on the left, the component on the right. */
function Spec({ label, children, block, wide }: { label: string; children: ReactNode; block?: boolean; wide?: boolean }) {
  return (
    <div className={wide ? 'grid gap-y-2' : 'grid items-start gap-x-8 gap-y-2 lg:grid-cols-[220px_1fr]'}>
      <p className="eyebrow pt-1.5">{label}</p>
      <div className={block ? 'min-w-0' : 'flex min-w-0 flex-wrap items-center gap-3'}>{children}</div>
    </div>
  )
}

function Swatch({ token, hex, use }: { token: string; hex?: string; use: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-10 w-10 shrink-0 rounded border border-rule-strong" style={{ background: `var(${token})` }} />
      <div className="min-w-0">
        <p className="font-mono text-xs text-fg">
          {token}
          {hex && <span className="text-muted"> {hex}</span>}
        </p>
        <p className="truncate text-xs text-muted">{use}</p>
      </div>
    </div>
  )
}

const stampOf = (c: CaseDetail) => ({
  outcome: c.outcome ?? null,
  status: c.status,
  vasp: c.top_vasp,
  confidence: c.confidence,
  interval: c.candidates.find((x) => x.vasp === c.top_vasp)?.confidence_interval,
  whatWouldChange: c.what_would_change[0],
})

const labelsOf = (c: CaseDetail) =>
  Object.fromEntries(c.graph.nodes.filter((n) => n.label).map((n) => [n.id, { entity: n.label!.entity, tier: n.label!.tier }]))

const labelColumns: Column<LabelOut>[] = [
  { key: 'entity', header: 'Owner', sortValue: (l) => l.entity, cell: (l) => <span className="font-medium">{l.entity}</span> },
  { key: 'address', header: 'Address', cell: (l) => <AddressChip address={l.address} chain={l.chain as Chain} /> },
  { key: 'chain', header: 'Chain', sortValue: (l) => l.chain, cell: (l) => <ChainBadge chain={l.chain as Chain} size="sm" /> },
  { key: 'tier', header: 'Tier', sortValue: (l) => l.tier, cell: (l) => <TierTag tier={l.tier} size="sm" /> },
  { key: 'label', header: 'Label', sortValue: (l) => l.label ?? null, cell: (l) => <span className="text-muted">{l.label}</span> },
]

export function KitPage() {
  const cases = useQuery({ queryKey: ['kit', 'cases'], queryFn: () => Promise.all(DEMO_CASES.map((id) => api.case(id))) })
  const labels = useQuery({ queryKey: ['kit', 'labels'], queryFn: () => api.labelSearch({ q: 'coindcx', limit: 10 }) })
  const request = useQuery({ queryKey: ['kit', 'request'], queryFn: () => api.request('demo-req-okx-001') })
  const toast = useToast()
  const [dialog, setDialog] = useState(false)
  const [replay, setReplay] = useState(0)
  const [tab, setTab] = useState('timeline')

  const [okx, abstain, sanctioned] = cases.data ?? []
  // One real labelled wallet per tier, from the fixtures' graphs.
  const byTier = new Map<Tier, GraphNode>()
  for (const c of cases.data ?? []) for (const n of c.graph.nodes) if (n.label && !byTier.has(n.label.tier)) byTier.set(n.label.tier, n)
  const candidates = (cases.data ?? []).flatMap((c) => c.candidates.map((x) => ({ ...x, chain: c.chain })))
  const flags = (cases.data ?? []).flatMap((c) => c.typology_flags)

  return (
    <>
      <PageHeader title="Component kit">
        Every component of VASP-FUSION in every state. The cases, labels and figures on this page are demonstration
        fixtures (the labelled addresses in them are real); nothing here is evidence.
      </PageHeader>

      {cases.isError && (
        <ErrorState title="The fixtures could not be loaded" detail={(cases.error as Error).message} onRetry={() => void cases.refetch()} />
      )}

      <Section title="Colour" note="Six brand colours that never change, and role tokens that switch with the theme. Saffron means the attributed exchange or the primary action, and nothing else.">
        <div className="grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-3">
          {BRAND.map(([token, hex, use]) => (
            <Swatch key={token} token={token} hex={hex} use={use} />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-x-6 gap-y-4 border-t border-dashed border-rule pt-6 lg:grid-cols-4">
          {ROLES.map(([token, use]) => (
            <Swatch key={token} token={token} use={use} />
          ))}
        </div>
      </Section>

      <Section title="Type" note="Bricolage Grotesque for page titles and the names on stamps. IBM Plex Sans for everything read. IBM Plex Mono for every address, hash and amount.">
        <Spec label="Display 40" block>
          <p className="display text-2xl">Draft request to CoinDCX</p>
        </Spec>
        <Spec label="Display 28" block>
          <p className="display text-xl">Where the funds went</p>
        </Spec>
        <Spec label="Display 20" block>
          <p className="display text-lg">Exchanges reached</p>
        </Spec>
        <Spec label="Body 16" block>
          <p className="max-w-prose text-base">The narrative of a case is set at 16: it is the paragraph an officer reads in full.</p>
        </Spec>
        <Spec label="Body 14" block>
          <p className="max-w-prose text-sm">Everything else is 14: tables, labels, controls, the sentences that say what to do next.</p>
        </Spec>
        <Spec label="Small 12" block>
          <p className="text-xs text-muted">Captions, tags and the figures under a meter.</p>
        </Spec>
        <Spec label="Field label" block>
          <p className="eyebrow">Exchanges reached</p>
        </Spec>
        <Spec label="Mono 14" block>
          <p className="break-all font-mono text-sm">{HERO_TRON}</p>
        </Spec>
        <Spec label="Mono 12, tabular" block>
          <p className="tabular font-mono text-xs">
            0123456789 · 2,652.22 USDT · 0.364594 BTC · {formatInr(4050000)}
          </p>
        </Spec>
      </Section>

      <Section title="Buttons" note="One primary action per screen, named for what it does. On a case it is always “Draft request to” the exchange.">
        <Spec label="Primary">
          <Button variant="primary">Draft request to OKX</Button>
          <Button variant="primary" disabled>
            Draft request to OKX
          </Button>
          <Button variant="primary" size="sm">
            Trace wallet
          </Button>
        </Spec>
        <Spec label="Secondary">
          <Button>Open case file</Button>
          <Button disabled>Open case file</Button>
          <Button size="sm" icon={<RotateCcw size={13} aria-hidden />}>
            Trace again
          </Button>
        </Spec>
        <Spec label="Ghost">
          <Button variant="ghost">Mark as sent</Button>
          <Button variant="ghost" size="sm">
            Verify
          </Button>
        </Spec>
        <Spec label="Danger">
          <Button variant="danger">Withdraw request</Button>
          <Button variant="danger" size="sm">
            Request a freeze
          </Button>
        </Spec>
      </Section>

      <Section title="Addresses and hashes" note="Shortened in the middle; whole on hover or keyboard focus; copy always copies the whole. A labelled address names its owner, with the tier as an icon and in the tooltip.">
        <Spec label="Unlabelled">
          <AddressChip address={HERO_TRON} chain="tron" />
          <AddressChip address={DEMO_BTC} chain="bitcoin" />
        </Spec>
        <Spec label="The suspect wallet">
          <AddressChip address={HERO_TRON} chain="tron" role="suspect" />
        </Spec>
        <Spec label="Labelled, by tier">
          {(['published_por', 'curated', 'explorer_tag', 'derived'] as Tier[]).map((tier) => {
            const node = byTier.get(tier)
            return node ? (
              <AddressChip key={tier} address={node.id} chain={node.chain} entity={node.label!.entity} tier={tier} />
            ) : (
              <Skeleton key={tier} width={220} height={28} />
            )
          })}
        </Spec>
        <Spec label="Whole (letters, records)">
          <AddressChip address={HERO_TRON} chain="tron" full />
        </Spec>
        <Spec label="Copy only (Hop Rail)">
          <AddressChip address={HERO_TRON} chain="tron" head={4} tail={4} actions="copy" />
        </Spec>
        <Spec label="Transaction hash">
          {okx ? (
            <>
              <TxHash hash={okx.hop_rail[0].tx_hash} chain={okx.chain} />
              <TxHash hash={okx.hop_rail[0].tx_hash} chain={okx.chain} full />
            </>
          ) : (
            <Skeleton width={220} height={24} />
          )}
        </Spec>
      </Section>

      <Section title="Chains" note="A dashed badge is a guess made while the address is still being typed.">
        <Spec label="All chains">
          {(Object.keys(CHAINS) as Chain[]).map((chain) => (
            <ChainBadge key={chain} chain={chain} />
          ))}
        </Spec>
        <Spec label="While typing">
          <ChainBadge chain="tron" tentative />
          <ChainBadge chain="ethereum" tentative />
          <ChainBadge chain="bitcoin" tentative />
        </Spec>
        <Spec label="Small">
          <ChainBadge chain="tron" size="sm" />
          <ChainBadge chain="bitcoin" size="sm" />
        </Spec>
      </Section>

      <Section title="Label tiers" note="How strong a label is, strongest first. Always an icon, words and a colour together.">
        <Spec label="Tags">
          {(['published_por', 'curated', 'explorer_tag', 'derived', null] as (Tier | null)[]).map((tier) => (
            <TierTag key={tier ?? 'none'} tier={tier} />
          ))}
        </Spec>
        <Spec label="Small">
          {(['published_por', 'curated', 'explorer_tag', 'derived', null] as (Tier | null)[]).map((tier) => (
            <TierTag key={tier ?? 'none'} tier={tier} size="sm" />
          ))}
        </Spec>
      </Section>

      <Section title="Outcome stamps" note="What a case came to. Attributed is solid saffron; insufficient evidence is dashed slate and says what would change it; sanctioned or mixer reached is seal red.">
        <Spec label="On a case">
          {cases.data ? (
            cases.data.map((c) => <OutcomeStamp key={c.id} {...stampOf(c)} size="lg" />)
          ) : (
            <Skeleton width={520} height={84} />
          )}
        </Spec>
        <Spec label="No result yet">
          <OutcomeStamp outcome={null} status="running" size="lg" />
          <OutcomeStamp outcome={null} status="failed" size="lg" />
        </Spec>
        <Spec label="In a table row">
          {cases.data?.map((c) => <OutcomeStamp key={c.id} {...stampOf(c)} />)}
          <OutcomeStamp outcome={null} status="queued" />
          <OutcomeStamp outcome={null} status="failed" />
        </Spec>
      </Section>

      <Section title="Proximity and confidence" note="Two meters, never one score. Proximity is how near the exchange is to the wallet. Confidence is how sure we are it is that exchange; the mark is the 0.60 bar a candidate must clear to be named.">
        {candidates.length === 0 && <Skeleton lines={3} />}
        {candidates.map((x) => (
          <Spec key={x.vasp + x.deposit_address} label={`${x.vasp} (fixture)`} block>
            <DualMeter
              proximityRank={x.proximity_rank}
              hops={x.hops}
              shareOfFunds={x.share_of_funds}
              timeToReachS={x.time_to_reach_s}
              confidence={x.confidence}
              interval={x.confidence_interval}
              className="max-w-[640px]"
            />
          </Spec>
        ))}
        {okx && (
          <>
            <Spec label="No range: rule confidence" block>
              <DualMeter
                proximityRank={okx.candidates[0].proximity_rank}
                hops={okx.candidates[0].hops}
                shareOfFunds={okx.candidates[0].share_of_funds}
                confidence={okx.candidates[0].confidence}
                interval={null}
                className="max-w-[640px]"
              />
            </Spec>
            <Spec label="Stacked (narrow column)" block>
              <DualMeter
                proximityRank={okx.candidates[0].proximity_rank}
                hops={okx.candidates[0].hops}
                shareOfFunds={okx.candidates[0].share_of_funds}
                timeToReachS={okx.candidates[0].time_to_reach_s}
                confidence={okx.candidates[0].confidence}
                interval={okx.candidates[0].confidence_interval}
                layout="stack"
                className="max-w-[300px]"
              />
            </Spec>
          </>
        )}
      </Section>

      <Section title="Amounts" note="In the asset that moved, in mono with tabular figures. The US dollar value follows only when it adds something.">
        <Spec label="Stablecoin">{okx && <Amount value={okx.hop_rail[0].amount} asset={okx.hop_rail[0].asset} usd={okx.hop_rail[0].amount_usd} />}</Spec>
        <Spec label="With a dollar value">
          {abstain && <Amount value={abstain.hop_rail[0].amount} asset={abstain.hop_rail[0].asset} usd={abstain.hop_rail[0].amount_usd} />}
        </Spec>
        <Spec label="Sizes">
          {okx && (
            <>
              <Amount value={okx.hop_rail[1].amount} asset="USDT" size="sm" />
              <Amount value={okx.hop_rail[1].amount} asset="USDT" />
              <Amount value={okx.hop_rail[1].amount} asset="USDT" size="lg" />
            </>
          )}
        </Spec>
        <Spec label="Reported loss">
          {okx?.amount_lost_inr != null && <span className="tabular font-mono text-sm">{formatInr(okx.amount_lost_inr)}</span>}
        </Spec>
      </Section>

      <Section title="Patterns and leads" note="Patterns in the traced funds. None of them decides the outcome. A lead is something to look into, kept apart from the answer.">
        <Spec label="With the sentence" block>
          <div className="flex max-w-prose flex-col gap-2">
            {flags.length === 0 && <Skeleton lines={2} />}
            {flags.map((flag, i) => (
              <TypologyFlag key={flag.code + i} flag={flag} />
            ))}
          </div>
        </Spec>
        <Spec label="Every pattern, compact">
          {PATTERNS.map(([code, severity]) => (
            <TypologyFlag key={code} compact flag={{ code, severity, wallet: '', text: '', figures: {}, tx_hashes: [] }} />
          ))}
        </Spec>
      </Section>

      <Section title="Hop Rail" note="The signature of a case: the suspect wallet, each hop with its ticket stub (amount, time taken), and the docket stamp it ends in. When a trace finishes, the rail extends hop by hop. That is the one animation in the app.">
        <Spec label="Attributed" block wide>
          <div className="flex flex-col items-start gap-3">
            {okx ? (
              <HopRail
                key={replay}
                className="w-full"
                suspect={{ address: okx.address, chain: okx.chain }}
                hops={okx.hop_rail}
                labels={labelsOf(okx)}
                stamp={stampOf(okx)}
                animate={replay > 0}
              />
            ) : (
              <Skeleton height={96} />
            )}
            <Button size="sm" icon={<RotateCcw size={13} aria-hidden />} onClick={() => setReplay((n) => n + 1)}>
              Replay the trace
            </Button>
          </div>
        </Spec>
        <Spec label="Insufficient evidence" block wide>
          {abstain ? (
            <HopRail suspect={{ address: abstain.address, chain: abstain.chain }} hops={abstain.hop_rail} labels={labelsOf(abstain)} stamp={stampOf(abstain)} />
          ) : (
            <Skeleton height={96} />
          )}
        </Spec>
        <Spec label="Sanctioned reached" block wide>
          {sanctioned ? (
            <HopRail
              suspect={{ address: sanctioned.address, chain: sanctioned.chain }}
              hops={sanctioned.hop_rail}
              labels={labelsOf(sanctioned)}
              stamp={stampOf(sanctioned)}
            />
          ) : (
            <Skeleton height={96} />
          )}
        </Spec>
        <Spec label="While tracing" block wide>
          <HopRail suspect={{ address: HERO_TRON, chain: 'tron' }} hops={[]} stamp={{ outcome: null, status: 'running' }} state="tracing" />
        </Spec>
      </Section>

      <Section title="Where the funds went" note="One bar for the whole of what the wallet sent. Kind is not told by hue: saffron is the exchange the case names, ink any other named party, red a sanctioned address or a mixer, and everything unresolved is hatched. Every part is named under the bar.">
        {FUNDS.map((f) => (
          <Spec key={f.total} label={f.named ? 'An exchange is named' : f.slices[0].kind === 'sanctioned' ? 'Sanctioned' : 'No exchange reached'} block wide>
            <FundsBar slices={f.slices} asset={f.asset} total={f.total} named={f.named} />
          </Spec>
        ))}
      </Section>

      <Section title="Evidence" note="The reasons behind a named exchange, in the backend’s own sentences, each with the transactions that prove it. The deposit-address model’s reasons are drawn as signed bars.">
        <Spec label="Sweep, path, fee payer" block>
          {okx ? <EvidenceList items={okx.candidates[0].evidence} chain={okx.chain} /> : <Skeleton lines={4} />}
        </Spec>
        <Spec label="Model reasons" block>
          <EvidenceList
            chain="tron"
            items={[
              // The three reasons the model gave for the real deposit address TCw8j3…LLcoV5 (tron-coindcx).
              { kind: 'model', text: 'Deposit-address model, for: it forwards 100% of what it receives to one wallet', weight: 2.2923, tx_hashes: [], tier: null },
              { kind: 'model', text: 'Deposit-address model, for: every outgoing transfer goes to one wallet', weight: 1.9244, tx_hashes: [], tier: null },
              { kind: 'model', text: 'Deposit-address model, for: it moves funds on about 21 seconds after they arrive', weight: 1.6002, tx_hashes: [], tier: null },
            ]}
          />
        </Spec>
      </Section>

      <Section title="Tabs" note="The index tabs of a file. One tab stop; the arrow keys move along them, Home and End jump to the ends. A count says how many records a tab holds.">
        <Spec label="Case records" block wide>
          <Tabs label="Case records" tabs={KIT_TABS} active={tab} onChange={setTab}>
            <p className="text-sm text-muted">The {KIT_TABS.find((t) => t.id === tab)!.label.toLowerCase()} of the case goes here.</p>
          </Tabs>
        </Spec>
      </Section>

      <Section title="Request status and routing slip" note="Where a request stands: an icon and a word. The routing slip is the slip on a file: a box per step in order, stamped with its day once it happened; a box not reached is dashed and empty.">
        <Spec label="Status" block wide>
          <div className="flex flex-wrap gap-2">
            {(['not_requested', ...STATUS_ORDER] as const).map((status) => (
              <StatusTag key={status} status={status} />
            ))}
          </div>
        </Spec>
        {request.data && (
          <>
            <Spec label="In a table row: a draft, then sent" block wide>
              <div className="flex flex-wrap gap-4">
                <RoutingSlip history={request.data.status_history.slice(0, 1)} status="drafted" />
                <RoutingSlip history={request.data.status_history} status={request.data.status} />
              </div>
            </Spec>
            <Spec label="Beside the letter, with who and the note of each step" block>
              <div className="max-w-[320px]">
                <RoutingSlip history={request.data.status_history} status={request.data.status} layout="column" />
              </div>
            </Spec>
          </>
        )}
      </Section>

      <Section title="Table" note="Sortable columns, a header that stays in view, rows that open with a click or Enter.">
        <Spec label="With rows" block>
          <DataTable
            caption="Labelled addresses"
            columns={labelColumns}
            rows={labels.data?.items ?? []}
            rowKey={(l) => l.chain + l.address}
            loading={labels.isPending}
            initialSort={{ key: 'label', dir: 'asc' }}
            maxHeight={280}
          />
        </Spec>
        <Spec label="Loading" block>
          <DataTable caption="Labelled addresses, loading" columns={labelColumns} rows={[]} rowKey={(l) => l.address} loading />
        </Spec>
        <Spec label="No rows" block>
          <DataTable
            caption="Labelled addresses, none found"
            columns={labelColumns}
            rows={[]}
            rowKey={(l) => l.address}
            empty="No label matches this search. Try the exchange’s name, or part of an address."
          />
        </Spec>
      </Section>

      <Section title="Empty, loading and error" note="An empty screen invites the next action. An error says what happened and what to do next.">
        <Spec label="Empty" block>
          <EmptyState
            title="No cases yet"
            icon={<FolderOpen size={22} aria-hidden />}
            action={<Button variant="primary">Trace a wallet</Button>}
          >
            Paste a wallet address in the search bar to open the first case.
          </EmptyState>
        </Spec>
        <Spec label="Loading" block>
          <div className="max-w-prose">
            <Skeleton lines={3} />
          </div>
        </Spec>
        <Spec label="Error, can retry" block>
          <ErrorState
            title="The cases could not be loaded"
            detail="Cannot reach the VASP-FUSION server. Check that it is running, then try again."
            onRetry={() => {}}
          />
        </Spec>
        <Spec label="Error, nothing to retry" block>
          <ErrorState title="This case could not be opened" detail="There is no case with this id. Check the link, or open the case from the list." />
        </Spec>
      </Section>

      <Section title="Toast and dialog" note="A toast confirms an action in the action’s own words. A dialog is for a decision that should not be made in passing.">
        <Spec label="Toast">
          <Button onClick={() => toast.show({ kind: 'success', title: 'Marked as sent', detail: 'The reply is due in 7 days.' })}>Show a toast</Button>
          <Button
            onClick={() =>
              toast.show({ kind: 'error', title: 'The request was not sent', detail: 'A draft cannot be sent. Approve it first.' })
            }
          >
            Show an error toast
          </Button>
        </Spec>
        <Spec label="Dialog">
          <Button onClick={() => setDialog(true)}>Open a dialog</Button>
          <Dialog
            open={dialog}
            onClose={() => setDialog(false)}
            title="Withdraw this request?"
            footer={
              <>
                <Button onClick={() => setDialog(false)}>Keep the request</Button>
                <Button variant="danger" onClick={() => setDialog(false)}>
                  Withdraw request
                </Button>
              </>
            }
          >
            The draft is set aside and its wallets can be put in a new request. Nothing has been sent to the exchange.
          </Dialog>
        </Spec>
      </Section>
    </>
  )
}
