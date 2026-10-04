import type { Tier } from '../api/models'
import { TIERS } from '../components/TierTag'
import type { FlowView, Role } from '../lib/caseGraph'
import { ROLE_NAMES, ROLE_ORDER } from './caseText'

const BOX = { w: 30, h: 20 }

/** The node shapes of the canvas, redrawn small in SVG (Cytoscape's shape names in flowStyle.ts). */
function shapePath(role: Role): { d?: string; circle?: number; rect?: number } {
  switch (role) {
    case 'suspect':
      return { circle: 8 }
    case 'intermediary':
      return { circle: 6.5 }
    case 'unknown':
      return { circle: 4 }
    case 'hub':
      return { d: 'M9 2h12l6 8-6 8H9l-6-8z' }
    case 'exchange':
    case 'exchange_hot':
      return { rect: 4 }
    case 'exchange_deposit':
      return { d: 'M4 3h15l8 7-8 7H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z' }
    case 'custodial_wallet':
      return { rect: 8 }
    case 'swap_service':
      return { d: 'M9 3h19l-7 14H2z' }
    case 'bridge':
      return { d: 'M15 1l10 9-10 9-10-9z' }
    case 'mixer':
      return { d: 'M3 3h24l-5 7 5 7H3l5-7z' }
    case 'sanctioned':
      return { d: 'M10 2h10l6 5v6l-6 5H10l-6-5V7z' }
  }
}

function RoleGlyph({ role }: { role: Role }) {
  const shape = shapePath(role)
  const fill = role === 'suspect' ? 'var(--fg)' : role === 'sanctioned' || role === 'mixer' ? 'var(--seal)' : role === 'hub' ? 'var(--surface-sunk)' : 'var(--surface)'
  const common = { fill, stroke: 'var(--fg)', strokeWidth: 1.5 }
  return (
    <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
      {shape.circle ? (
        <circle cx={BOX.w / 2} cy={BOX.h / 2} r={shape.circle} {...common} />
      ) : shape.rect ? (
        <rect x={3} y={3} width={24} height={14} rx={shape.rect} {...common} />
      ) : (
        <path d={shape.d} {...common} />
      )}
      {role === 'sanctioned' && <rect x={10} y={8.5} width={10} height={3} rx={1} fill="var(--on-seal)" />}
    </svg>
  )
}

/** The border a wallet wears for the tier of its label: the same five as TierTag. */
function TierGlyph({ tier }: { tier: Tier | 'none' }) {
  const teal = 'var(--verified-text)'
  const box = { x: 3, y: 3, width: 24, height: 14, rx: 4, fill: 'var(--surface)' }
  return (
    <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
      {tier === 'published_por' && (
        <>
          <rect {...box} stroke={teal} strokeWidth={1.5} />
          <rect x={6} y={6} width={18} height={8} rx={2} fill="none" stroke={teal} strokeWidth={1.5} />
        </>
      )}
      {tier === 'curated' && <rect {...box} fill="var(--verified-wash)" stroke={teal} strokeWidth={2.5} />}
      {tier === 'explorer_tag' && <rect {...box} stroke={teal} strokeWidth={2.5} strokeDasharray="0.1 4" strokeLinecap="round" />}
      {tier === 'derived' && <rect {...box} stroke="var(--fg-muted)" strokeWidth={2} />}
      {tier === 'none' && <rect {...box} stroke="var(--rule-strong)" strokeWidth={1.5} strokeDasharray="4 3" />}
    </svg>
  )
}

const TIER_ORDER: (Tier | 'none')[] = ['published_por', 'curated', 'explorer_tag', 'derived', 'none']

const item = 'flex items-center gap-1.5 whitespace-nowrap text-xs text-fg'

/** How to read the picture, in words: only the shapes and borders this case uses. */
export function GraphLegend({ view, named }: { view: FlowView; named?: string | null }) {
  const wallets = view.nodes.filter((n) => n.kind !== 'more')
  const roles = ROLE_ORDER.filter((role) => wallets.some((n) => n.role === role))
  const tiers = TIER_ORDER.filter((tier) => wallets.some((n) => n.role !== 'suspect' && (n.tier ?? 'none') === tier))
  const hasMore = view.nodes.some((n) => n.kind === 'more')
  const hasInbound = view.edges.some((e) => e.direction === 'inbound')
  const hasNamed = view.nodes.some((n) => n.named)

  return (
    <div role="group" aria-label="How to read the graph" className="grid gap-x-6 gap-y-2 border-t border-rule px-4 py-3 sm:grid-cols-[auto_1fr]">
      <span className="eyebrow pt-0.5">Shape: role</span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {roles.map((role) => (
          <li key={role} className={item}>
            <RoleGlyph role={role} />
            {ROLE_NAMES[role]}
          </li>
        ))}
        {hasMore && (
          <li className={item}>
            <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
              <rect x={2} y={4} width={26} height={12} rx={3} fill="var(--surface-sunk)" stroke="var(--fg-muted)" strokeWidth={1.5} strokeDasharray="4 3" />
            </svg>
            The rest of a hop, not drawn one by one
          </li>
        )}
      </ul>
      <span className="eyebrow pt-0.5">Border: label</span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {tiers.map((tier) => (
          <li key={tier} className={item}>
            <TierGlyph tier={tier} />
            {TIERS[tier].name}
          </li>
        ))}
        {hasNamed && named && (
          <li className={item}>
            <span aria-hidden className="mx-[3px] h-3.5 w-6 shrink-0 rounded bg-saffron" />
            {named}, the exchange this case names
          </li>
        )}
      </ul>
      <span className="eyebrow pt-0.5">Line: transfer</span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        <li className={item}>
          <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
            <path d="M2 6h26" stroke="var(--rule-strong)" strokeWidth={1.5} />
            <path d="M2 14h26" stroke="var(--rule-strong)" strokeWidth={5} />
          </svg>
          Width is the amount
        </li>
        <li className={item}>
          <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
            <path d="M2 10h26" stroke="var(--fg)" strokeWidth={3} />
          </svg>
          The path on the Hop Rail
        </li>
        {hasInbound && (
          <li className={item}>
            <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
              <path d="M2 10h26" stroke="var(--rule-strong)" strokeWidth={2.5} strokeDasharray="7 4" />
            </svg>
            Money coming in
          </li>
        )}
      </ul>
    </div>
  )
}
