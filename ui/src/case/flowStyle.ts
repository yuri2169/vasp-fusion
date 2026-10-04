/** A FlowView as Cytoscape elements, and the stylesheet that draws them.
 *
 *  What the picture encodes (ui/DESIGN.md, "The fund-flow graph"):
 *    icon         the wallet's role, inside a square tile (roleIcons.ts)
 *    tile size    the amount that passed through it: three sizes
 *    border       the tier of its label, in the label colour (the same vocabulary as TierTag)
 *    chain colour the suspect wallet, the hops and the main path: on-chain facts
 *    label wash   a wallet a label names: an exchange, a bridge, a swap service
 *    fusion fill  a wallet of the exchange the case names, and nothing else
 *    danger fill  a sanctioned address or a mixer
 *    data colour  an unlabelled wallet the trail stops at
 *    edge width   the amount; hairlines, dashed for money coming in */
import type { ElementDefinition, StylesheetJsonBlock } from 'cytoscape'
import { THREATS } from '../components/ThreatChip'
import type { FlowRisk, RiskClass } from '../api/models'
import { RISK_ORDER, RISK_WORDS } from '../components/RiskTag'
import { edgeWidth, nodeXY, type FlowNode, type FlowView, type Role } from '../lib/caseGraph'
import { formatAmount, truncateMiddle } from '../lib/format'
import { iconMarkup, ROLE_ICONS, type IconNode } from './roleIcons'

/** The role tokens the canvas needs, resolved to colours (a canvas cannot read CSS variables). */
export interface ThemeColors {
  fg: string
  muted: string
  surface: string
  sunk: string
  ruleStrong: string
  saffron: string
  chain: string
  chainWash: string
  data: string
  verifiedText: string
  verifiedWash: string
  seal: string
  onSeal: string
}

/** The light theme, for when the page's tokens cannot be read (tests, a canvas made off-page). */
export const FALLBACK_THEME: ThemeColors = {
  fg: '#0E1C27',
  muted: '#4A5B69',
  surface: '#FFFFFF',
  sunk: '#F3F5F7',
  ruleStrong: '#56646F',
  saffron: '#8C5B0E',
  chain: '#2D6A9F',
  chainWash: '#EAF1F7',
  data: '#5C6B78',
  verifiedText: '#7B4B94',
  verifiedWash: '#F4EEF7',
  seal: '#A2453B',
  onSeal: '#FFFFFF',
}

const TOKENS: Record<keyof ThemeColors, string> = {
  fg: '--fg',
  muted: '--fg-muted',
  surface: '--surface',
  sunk: '--surface-sunk',
  ruleStrong: '--rule-strong',
  saffron: '--saffron',
  chain: '--chain',
  chainWash: '--chain-wash',
  data: '--data',
  verifiedText: '--verified-text',
  verifiedWash: '--verified-wash',
  seal: '--seal',
  onSeal: '--on-seal',
}

export function readTheme(el: Element = document.documentElement): ThemeColors {
  const css = getComputedStyle(el)
  const out = { ...FALLBACK_THEME }
  for (const [key, token] of Object.entries(TOKENS) as [keyof ThemeColors, string][]) {
    const value = css.getPropertyValue(token).trim()
    if (value) out[key] = value
  }
  return out
}

/** The three tile sizes, by the amount that passed through the wallet. */
export const TILE = { s: 28, m: 36, l: 46 } as const
export type TileSize = keyof typeof TILE
/** A wallet that was not followed further: a small dashed tile with no icon. */
const UNFOLLOWED = 16

const through = (n: Pick<FlowNode, 'received' | 'sent'>) => Math.max(n.received, n.sent)

/** Large from half of the largest amount in the picture, medium from a tenth, small below.
 *  The wallet the case is about is always large. */
export function tileSize(n: FlowNode, most: number): TileSize {
  if (n.role === 'suspect') return 'l'
  const share = most > 0 ? through(n) / most : 0
  return share >= 0.5 ? 'l' : share >= 0.1 ? 'm' : 's'
}

const sideOf = (n: FlowNode, most: number) => (n.role === 'unknown' && n.kind === 'wallet' ? UNFOLLOWED : TILE[tileSize(n, most)])

/** Where a wallet's caption sits: just over its tile. */
export const captionY = (y: number, side: number) => y - side / 2 - 9

/** What is written over a node: the owner a label names, or what the wallet is to the case. */
function captionOf(n: FlowNode): string | null {
  if (n.role === 'suspect') return 'Suspect'
  // a tagged wallet says what it is tagged as, in words, beside the warning sign
  if (n.label?.threat) return `\u26A0 ${THREATS[n.label.threat].name}: ${n.label.threat_entity ?? n.entity ?? ''}`.replace(/: $/, '')
  if (n.entity) return n.entity
  if (n.role === 'hub') return 'Busy wallet'
  return null
}

/** The mark a flagged transfer wears on the canvas, with its class in words beside it. */
export const RISK_MARK = '▲'

/** The highest class among the transfers one drawn line stands for; undefined when all are Low. */
export function edgeRisk(transferIds: string[], flows?: ReadonlyMap<string, FlowRisk>): RiskClass | undefined {
  let top: RiskClass | undefined
  for (const id of transferIds) {
    const klass = flows?.get(id)?.risk_class
    if (klass && (!top || RISK_ORDER.indexOf(klass) > RISK_ORDER.indexOf(top))) top = klass
  }
  return top
}

/** `flows`: the case's transfers above Low (risk.flows), by transfer id. A line that stands for
 *  one is marked and says its class in words; High and Severe are also drawn in the danger colour. */
export function toElements(view: FlowView, flows?: ReadonlyMap<string, FlowRisk>): ElementDefinition[] {
  const elements: ElementDefinition[] = []
  const most = view.nodes.reduce((max, n) => (n.kind === 'more' ? max : Math.max(max, through(n))), 0)
  for (const n of view.nodes) {
    const position = nodeXY(n)
    const side = sideOf(n, most)
    elements.push({
      group: 'nodes',
      data: {
        id: n.id,
        kind: n.kind,
        role: n.role,
        tier: n.tier ?? 'none',
        named: n.named ? 1 : 0,
        onPath: n.onPath ? 1 : 0,
        side,
        label:
          n.kind === 'more'
            ? `+${n.members.length.toLocaleString('en-US')} wallets`
            : n.kind === 'cluster'
              ? `${n.members.length} wallets`
              : truncateMiddle(n.id, 4, 4),
      },
      position,
    })
    const caption = captionOf(n)
    if (caption)
      elements.push({
        group: 'nodes',
        data: { id: `caption:${n.id}`, owner: n.id, label: caption },
        position: { x: position.x, y: captionY(position.y, side) },
        classes: n.label?.threat && n.role !== 'suspect' ? 'caption threat' : 'caption',
        selectable: false,
        grabbable: false,
      })
  }
  for (const e of view.edges) {
    const risk = edgeRisk(e.transfers.map((t) => t.id), flows)
    elements.push({
      group: 'edges',
      data: {
        id: e.id,
        source: e.source,
        target: e.target,
        // Hairlines: the amount still sets the width, within a narrower range than the layout's own.
        width: Math.max(1, Math.round(edgeWidth(e.amount, view.maxAmount) * 5.5) / 10),
        inbound: e.direction === 'inbound' ? 1 : 0,
        onPath: e.onPath ? 1 : 0,
        // Written on the main path and on the larger flows; the rest say it on hover.
        label: risk
          ? // two short lines: a flagged transfer is often the one between two close tiles
            `${RISK_MARK} ${RISK_WORDS[risk]} risk\n${formatAmount(e.amount, e.asset)}`
          : e.onPath || e.amount >= view.maxAmount * 0.1
            ? formatAmount(e.amount, e.asset)
            : '',
        ...(risk ? { risk } : {}),
      },
    })
  }
  return elements
}

/** A role's icon as an image the canvas can draw, in one colour. */
export function iconUri(node: IconNode, colour: string): string {
  const body = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="${colour}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${iconMarkup(node)}</svg>`
  return `data:image/svg+xml;utf8,${encodeURIComponent(body)}`
}

/** A tile's fill and the colour of the icon on it, by what the wallet is to the case.
 *  Colour repeats what the icon and the border already say; it is never the only signal. */
export function tileLook(role: Role, t: ThemeColors): { fill: string; ink: string } {
  switch (role) {
    case 'suspect':
      return { fill: t.chain, ink: t.surface }
    case 'intermediary':
      return { fill: t.chainWash, ink: t.chain }
    case 'unknown':
      return { fill: t.surface, ink: t.data }
    case 'hub':
      return { fill: t.data, ink: t.surface }
    case 'mixer':
    case 'sanctioned':
      return { fill: t.seal, ink: t.onSeal }
    default:
      return { fill: t.verifiedWash, ink: t.verifiedText }
  }
}

const ROLES = Object.keys(ROLE_ICONS) as Role[]

export function stylesheet(t: ThemeColors): StylesheetJsonBlock[] {
  const icon = (role: Role, colour: string) => {
    const node = ROLE_ICONS[role]
    return node ? { 'background-image': iconUri(node, colour), 'background-width': '58%', 'background-height': '58%', 'background-clip': 'none' } : {}
  }

  // Cytoscape's own types want exact literals for shapes and styles; these are checked by
  // running the stylesheet through Cytoscape in flowStyle.test.ts.
  return [
    {
      selector: 'node',
      style: {
        shape: 'rectangle',
        'background-color': t.surface,
        'border-width': 1,
        'border-style': 'dashed',
        'border-color': t.chain,
        label: 'data(label)',
        'font-family': '"Spline Sans Mono", ui-monospace, monospace',
        // 14 on the canvas, so that a graph drawn at three-quarter size still reads at 10 or more.
        'font-size': 13,
        color: t.muted,
        'text-valign': 'bottom',
        'text-margin-y': 5,
        'min-zoomed-font-size': 7,
      },
    },

    // --- border: the tier of the label ------------------------------------
    { selector: 'node[tier = "none"]', style: { 'border-style': 'dashed', 'border-width': 1, 'border-color': t.chain } },
    { selector: 'node[tier = "derived"]', style: { 'border-style': 'solid', 'border-width': 1.5, 'border-color': t.muted } },
    { selector: 'node[tier = "explorer_tag"]', style: { 'border-style': 'dotted', 'border-width': 2, 'border-color': t.verifiedText } },
    {
      selector: 'node[tier = "curated"]',
      style: { 'border-style': 'solid', 'border-width': 2, 'border-color': t.verifiedText, 'background-color': t.verifiedWash },
    },
    { selector: 'node[tier = "published_por"]', style: { 'border-style': 'double', 'border-width': 4, 'border-color': t.verifiedText } },

    // --- tile: three sizes, by the amount that passed through --------------
    { selector: 'node[side]', style: { width: 'data(side)', height: 'data(side)' } },

    // --- tile: the role, as a fill and an icon ----------------------------
    ...ROLES.map((role) => {
      const look = tileLook(role, t)
      return { selector: `node[role = "${role}"]`, style: { 'background-color': look.fill, ...icon(role, look.ink) } }
    }),
    { selector: 'node[role = "suspect"]', style: { 'border-style': 'solid', 'border-width': 1, 'border-color': t.chain } },
    { selector: 'node[role = "unknown"]', style: { 'border-color': t.data } },
    { selector: 'node[role = "hub"]', style: { 'border-style': 'solid', 'border-color': t.data } },
    { selector: 'node[role = "mixer"], node[role = "sanctioned"]', style: { 'border-style': 'solid', 'border-width': 1, 'border-color': t.fg } },

    // --- the exchange the case names: the one thing filled in the fusion colour ---
    { selector: 'node[named = 1]', style: { 'background-color': t.saffron } },
    // its icon is drawn in the paper colour, so it reads on that fill
    ...ROLES.filter((role) => ROLE_ICONS[role]).map((role) => ({ selector: `node[named = 1][role = "${role}"]`, style: icon(role, t.surface) })),

    // --- a group of one exchange's wallets: drawn as a stack --------------
    {
      selector: 'node[kind = "cluster"]',
      style: { ghost: 'yes', 'ghost-offset-x': 4, 'ghost-offset-y': -4, 'ghost-opacity': 0.45 },
    },

    // --- the rest of a hop in a large graph: one quiet node, not a wallet -----
    {
      selector: 'node[kind = "more"]',
      style: {
        shape: 'rectangle',
        width: 58,
        height: 26,
        'background-color': t.sunk,
        'background-image': 'none',
        'border-style': 'dashed',
        'border-width': 1,
        'border-color': t.muted,
        'font-family': '"Public Sans", system-ui, sans-serif',
        color: t.fg,
      },
    },

    // --- the owner's name over a node -------------------------------------
    // (a threat-tagged wallet's caption is in the danger colour, after the plain rule below)
    {
      selector: 'node.caption',
      style: {
        width: 1,
        height: 1,
        'background-opacity': 0,
        'border-width': 0,
        events: 'no',
        'font-family': 'Archivo, system-ui, sans-serif',
        'font-weight': 700,
        'font-size': 14,
        color: t.fg,
        'text-valign': 'top',
        'text-margin-y': 0,
        'text-background-color': t.surface,
        'text-background-opacity': 0.85,
        'text-background-padding': '2px',
      },
    },
    { selector: 'node.caption.threat', style: { color: t.seal } },

    // --- transfers --------------------------------------------------------
    {
      selector: 'edge',
      style: {
        width: 'data(width)',
        // Straight lines, one per pair of wallets. Square ("taxi") routing was tried and is tidier
        // on a small case, but it runs different transfers along one trunk, and then the picture
        // no longer says which wallet paid which.
        'curve-style': 'bezier',
        'line-color': t.ruleStrong,
        'target-arrow-color': t.ruleStrong,
        'target-arrow-shape': 'triangle',
        'arrow-scale': 0.8,
        label: 'data(label)',
        'font-family': '"Spline Sans Mono", ui-monospace, monospace',
        'font-size': 12,
        color: t.fg,
        'text-background-color': t.surface,
        'text-background-opacity': 1,
        'text-background-padding': '3px',
        'text-background-shape': 'rectangle',
        'min-zoomed-font-size': 7,
      },
    },
    { selector: 'edge[onPath = 1]', style: { 'line-color': t.chain, 'target-arrow-color': t.chain } },
    // A flagged transfer: the label says the class; High and Severe also take the danger colour.
    { selector: 'edge[risk = "high"], edge[risk = "severe"]', style: { 'line-color': t.seal, 'target-arrow-color': t.seal, color: t.seal, 'font-weight': 600 } },
    { selector: 'edge[risk]', style: { 'text-wrap': 'wrap', 'font-size': 11 } },
    { selector: 'edge[inbound = 1]', style: { 'line-style': 'dashed', 'line-dash-pattern': [7, 5], 'line-opacity': 0.7 } },

    // --- looking at one wallet: its path stays, the rest steps back --------
    { selector: '.dim', style: { opacity: 0.2 } },
    // --- the replay: what has not moved yet is not drawn ---------------------
    { selector: '.ahead', style: { visibility: 'hidden' } },
    { selector: 'node.sel', style: { 'underlay-color': t.fg, 'underlay-opacity': 0.14, 'underlay-padding': 8, 'underlay-shape': 'rectangle' } },
    { selector: 'node.hover', style: { 'underlay-color': t.fg, 'underlay-opacity': 0.08, 'underlay-padding': 6, 'underlay-shape': 'rectangle' } },
  ] as StylesheetJsonBlock[]
}
