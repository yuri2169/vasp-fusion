import type { Tier } from '../api/models'
import { TIERS } from '../components/TierTag'
import type { FlowView, Role } from '../lib/caseGraph'
import { ROLE_NAMES, ROLE_ORDER } from './caseText'
import { RISK_MARK } from './flowStyle'
import { iconMarkup, ROLE_ICONS } from './roleIcons'

const BOX = { w: 30, h: 20 }

/** A tile's colours as on the canvas (flowStyle.ts, tileLook), in the page's own tokens. */
function tileVars(role: Role): { fill: string; ink: string; stroke: string } {
  switch (role) {
    case 'suspect':
      return { fill: 'var(--chain)', ink: 'var(--surface)', stroke: 'var(--chain)' }
    case 'intermediary':
      return { fill: 'var(--chain-wash)', ink: 'var(--chain)', stroke: 'var(--chain)' }
    case 'unknown':
      return { fill: 'var(--surface)', ink: 'var(--data)', stroke: 'var(--data)' }
    case 'hub':
      return { fill: 'var(--data)', ink: 'var(--surface)', stroke: 'var(--data)' }
    case 'mixer':
    case 'sanctioned':
      return { fill: 'var(--danger)', ink: 'var(--on-seal)', stroke: 'var(--ink)' }
    default:
      return { fill: 'var(--network-wash)', ink: 'var(--network)', stroke: 'var(--network)' }
  }
}

/** The tile of the canvas, redrawn small: the same square, fill and icon. */
function RoleGlyph({ role }: { role: Role }) {
  const look = tileVars(role)
  const icon = ROLE_ICONS[role]
  const side = icon ? 20 : 12
  return (
    <svg aria-hidden width={BOX.h} height={BOX.h} viewBox="0 0 20 20" className="shrink-0">
      <rect x={(20 - side) / 2 + 0.5} y={(20 - side) / 2 + 0.5} width={side - 1} height={side - 1} fill={look.fill} stroke={look.stroke} strokeDasharray={icon ? undefined : '3 2'} />
      {icon && (
        <g
          transform="translate(4 4) scale(0.5)"
          fill="none"
          stroke={look.ink}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          dangerouslySetInnerHTML={{ __html: iconMarkup(icon) }}
        />
      )}
    </svg>
  )
}

/** The border a wallet wears for the tier of its label: the same five as TierTag. */
function TierGlyph({ tier }: { tier: Tier | 'none' }) {
  const teal = 'var(--network)'
  const box = { x: 3, y: 3, width: 24, height: 14, fill: 'var(--surface)' }
  return (
    <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
      {tier === 'published_por' && (
        <>
          <rect {...box} stroke={teal} strokeWidth={1.5} />
          <rect x={6} y={6} width={18} height={8} fill="none" stroke={teal} strokeWidth={1.5} />
        </>
      )}
      {tier === 'curated' && <rect {...box} fill="var(--network-wash)" stroke={teal} strokeWidth={2} />}
      {tier === 'explorer_tag' && <rect {...box} stroke={teal} strokeWidth={2} strokeDasharray="2 3" />}
      {tier === 'derived' && <rect {...box} stroke="var(--ink-soft)" strokeWidth={1.5} />}
      {tier === 'none' && <rect {...box} stroke="var(--chain)" strokeWidth={1} strokeDasharray="4 3" />}
    </svg>
  )
}

const TIER_ORDER: (Tier | 'none')[] = ['published_por', 'curated', 'explorer_tag', 'derived', 'none']

const item = 'flex items-center gap-1.5 whitespace-nowrap text-sm text-fg'

/** How to read the picture, in words: only the shapes and borders this case uses. */
export function GraphLegend({ view, named, flagged = false }: { view: FlowView; named?: string | null; flagged?: boolean }) {
  const wallets = view.nodes.filter((n) => n.kind !== 'more' && n.kind !== 'fan')
  const hasFan = view.nodes.some((n) => n.kind === 'fan')
  const roles = ROLE_ORDER.filter((role) => wallets.some((n) => n.role === role))
  const tiers = TIER_ORDER.filter((tier) => wallets.some((n) => n.role !== 'suspect' && (n.tier ?? 'none') === tier))
  const hasMore = view.nodes.some((n) => n.kind === 'more')
  const hasInbound = view.edges.some((e) => e.direction === 'inbound')
  const hasNamed = view.nodes.some((n) => n.named)

  return (
    <div role="group" aria-label="How to read the graph" className="grid gap-x-6 gap-y-2 border-t border-rule px-4 py-3 sm:grid-cols-[auto_1fr]">
      <span className="colhead pt-1">Icon: role</span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {roles.map((role) => (
          <li key={role} className={item}>
            <RoleGlyph role={role} />
            {ROLE_NAMES[role]}
          </li>
        ))}
        <li className={item}>
          <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
            <rect x={0.5} y={12.5} width={5} height={5} fill="none" stroke="var(--ink-soft)" />
            <rect x={7.5} y={9.5} width={8} height={8} fill="none" stroke="var(--ink-soft)" />
            <rect x={17.5} y={5.5} width={12} height={12} fill="none" stroke="var(--ink-soft)" />
          </svg>
          A larger tile carried more of the money
        </li>
        {hasMore && (
          <li className={item}>
            <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
              <rect x={2} y={4} width={26} height={12} fill="var(--surface-2)" stroke="var(--ink-soft)" strokeWidth={1} strokeDasharray="4 3" />
            </svg>
            The rest of a hop, not drawn one by one
          </li>
        )}
        {hasFan && (
          <li className={item}>
            <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
              <rect x={2} y={4} width={26} height={12} fill="var(--surface-2)" stroke="var(--chain)" strokeWidth={1} strokeDasharray="4 3" />
            </svg>
            Several small wallets drawn as one (click it to open them)
          </li>
        )}
      </ul>
      <span className="colhead pt-1">Border: label</span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        {tiers.map((tier) => (
          <li key={tier} className={item}>
            <TierGlyph tier={tier} />
            {TIERS[tier].name}
          </li>
        ))}
        {hasNamed && named && (
          <li className={item}>
            <span aria-hidden className="mx-[3px] h-3.5 w-6 shrink-0 bg-fusion" />
            {named}, the exchange this case names
          </li>
        )}
      </ul>
      <span className="colhead pt-1">Line: transfer</span>
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5">
        <li className={item}>
          <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
            <path d="M2 6h26" stroke="var(--rule-strong)" strokeWidth={1} />
            <path d="M2 14h26" stroke="var(--rule-strong)" strokeWidth={4} />
          </svg>
          Width is the amount
        </li>
        <li className={item}>
          <svg aria-hidden width={BOX.w} height={BOX.h} viewBox={`0 0 ${BOX.w} ${BOX.h}`} className="shrink-0">
            <path d="M2 10h26" stroke="var(--chain)" strokeWidth={2} />
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
        {flagged && (
          <li className={item}>
            <span aria-hidden className="inline-flex w-[30px] shrink-0 justify-center font-mono text-sm font-semibold text-danger">
              {RISK_MARK}
            </span>
            A flagged transfer, with its risk class in words (the Risk tab says why)
          </li>
        )}
      </ul>
    </div>
  )
}
