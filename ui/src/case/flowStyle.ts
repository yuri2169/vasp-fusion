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
import { CHAINS } from '../lib/chains'
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
/** A wallet that is only context: smaller still, and grey. */
export const CONTEXT_TILE = 12

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

/** The mark a cross-chain line wears on the canvas, before the bridge's name. */
export const BRIDGE_MARK = '\u21C4'
const ARROW = '\u2192'
const chainCode = (chain: keyof typeof CHAINS) => CHAINS[chain].code

/** What a tile prints under its icon: the short address, with the chain's code first when
 *  the wallet is on another chain than the case (its id is then `chain:address`). */
export function tileLabel(id: string): string {
  const at = id.indexOf(':')
  const chain = at > 0 ? id.slice(0, at) : ''
  return chain in CHAINS ? `${CHAINS[chain as keyof typeof CHAINS].code} ${truncateMiddle(id.slice(at + 1), 4, 4)}` : truncateMiddle(id, 4, 4)
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
  const most = view.nodes.reduce((max, n) => (n.kind === 'more' || n.kind === 'fan' || n.context ? max : Math.max(max, through(n))), 0)
  for (const n of view.nodes) {
    const position = nodeXY(n)
    if (n.context) {
      // quiet: a small grey tile, named only when pointed at or clicked
      elements.push({
        group: 'nodes',
        data: {
          id: n.id,
          kind: n.kind,
          context: 1,
          side: CONTEXT_TILE,
          label: '',
          // a group says how many inside its own tile; a wallet is named when asked
          name: n.kind === 'ctxmore' ? `+${n.members.length.toLocaleString('en-US')}` : n.entity ? `${n.entity} · ${tileLabel(n.id)}` : tileLabel(n.id),
        },
        position,
        classes: n.kind === 'ctxmore' ? 'named' : undefined,
      })
      continue
    }
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
            : n.kind === 'fan'
              ? `${fanWords(n)}\n${formatAmount(through(n), view.asset)}`
              : n.kind === 'cluster'
              ? `${n.members.length} wallets`
              : tileLabel(n.id),
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
    if (e.context) {
      elements.push({ group: 'edges', data: { id: e.id, source: e.source, target: e.target, context: 1, width: 1, label: '' } })
      continue
    }
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
        ...(e.bridge ? { bridge: 1 } : {}),
        // A line of a fan says its amount beside its own wallet, never on the shared trunk; the
        // group's line says nothing, its node carries the total.
        ...(e.fan ? { fan: e.fan, ...(fanEnd(e).startsWith('fan:') ? {} : { stub: formatAmount(e.amount, e.asset) }) } : {}),
        // Written on the main path and on the larger flows; the rest say it on hover.
        label: e.fan
          ? ''
          : e.bridge
          ? // a crossing always says so: both chains and what arrived (the bridge tile it leaves is named)
            `${BRIDGE_MARK} ${chainCode(e.bridge.source_chain)} ${ARROW} ${e.bridge.dest_chain ? chainCode(e.bridge.dest_chain) : '?'}\n${formatAmount(e.amount, e.asset)}`
          : risk
          ? // two short lines: a flagged transfer is often the one between two close tiles
            `${RISK_MARK} ${RISK_WORDS[risk]} risk\n${formatAmount(e.amount, e.asset)}`
          : e.onPath || e.amount >= view.maxAmount * 0.1
            ? formatAmount(e.amount, e.asset)
            : '',
        ...(risk ? { risk } : {}),
      },
    })
  }
  return placeLabels(elements)
}

const fanEnd = (e: { fan?: 'in' | 'out'; source: string; target: string }) => (e.fan === 'in' ? e.source : e.target)

/** What a fan's node says: how many wallets it stands for and which way their money went. */
export function fanWords(n: Pick<FlowNode, 'members' | 'fan'>): string {
  const wallets = `${n.members.length.toLocaleString('en-US')} ${n.members.length === 1 ? 'wallet' : 'wallets'}`
  return n.fan?.side === 'out' ? `${wallets} paid` : `${wallets} paid in`
}

/** How far from its own tile's edge a fan's line turns onto the trunk, and where its amount sits. */
const FAN_TRUNK_IN = 112
const FAN_TRUNK_OUT = 38
const STUB_OFFSET = 62

export type Box = { x1: number; y1: number; x2: number; y2: number }
const overlap = (a: Box, b: Box) => a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2
const lines = (text: string) => text.split('\n')
const widest = (text: string) => lines(text).reduce((max, l) => Math.max(max, l.length), 0)
const wide = (kind: unknown) => kind === 'more' || kind === 'fan'

/** Where the text of the picture is: each tile, what is written under and over it, the amount
 *  beside each wallet of a fan, and (`labels`) the amount written on each line. The sizes are
 *  the stylesheet's (mono 12 on a line, 13 under a tile, bold 14 over it), a little generous. */
export function textBoxes(elements: ElementDefinition[]): { fixed: Box[]; labels: Map<string, Box> } {
  const fixed: Box[] = []
  const at = new Map<string, { x: number; y: number }>()
  for (const el of elements) {
    if (el.group !== 'nodes' || !el.position) continue
    const { x, y } = el.position
    const text: string = el.data.label ?? ''
    if (el.data.owner) {
      const half = (text.length * 8.4) / 2 + 3
      fixed.push({ x1: x - half, y1: y - 20, x2: x + half, y2: y })
      continue
    }
    at.set(el.data.id!, el.position)
    const side = wide(el.data.kind) ? 58 : (el.data.side ?? 28)
    const tall = wide(el.data.kind) ? 26 : side
    fixed.push({ x1: x - side / 2, y1: y - tall / 2, x2: x + side / 2, y2: y + tall / 2 })
    const half = (widest(text) * 7.9) / 2
    if (text) fixed.push({ x1: x - half, y1: y + tall / 2 + 4, x2: x + half, y2: y + tall / 2 + 6 + lines(text).length * 16 })
  }
  const labels = new Map<string, Box>()
  for (const el of elements) {
    if (el.group !== 'edges') continue
    if (el.data.stub) {
      // beside the fan's own wallet, on the level part of its line
      const end = at.get(el.data.fan === 'in' ? el.data.source : el.data.target)
      if (!end) continue
      const cx = end.x + (el.data.fan === 'in' ? 1 : -1) * (STUB_OFFSET + 16)
      const half = (el.data.stub.length * 6.7) / 2 + 3
      fixed.push({ x1: cx - half, y1: end.y - 9, x2: cx + half, y2: end.y + 9 })
      continue
    }
    const a = at.get(el.data.source)
    const b = at.get(el.data.target)
    const text: string = el.data.label ?? ''
    if (!a || !b || !text) continue
    const half = (widest(text) * 7.3) / 2 + 3
    const tall = (lines(text).length * 15) / 2 + 3
    labels.set(el.data.id!, { x1: (a.x + b.x) / 2 - half, y1: (a.y + b.y) / 2 - tall, x2: (a.x + b.x) / 2 + half, y2: (a.y + b.y) / 2 + tall })
  }
  return { fixed, labels }
}

/** An amount is written on a line only where there is room for it: a label that would sit on a
 *  tile, on the text under or over a tile, or on a label already placed is left to the hover
 *  card. The crossing of a bridge, a flagged transfer and the Hop Rail's path are placed first,
 *  then the larger amounts. */
export function placeLabels(elements: ElementDefinition[]): ElementDefinition[] {
  const { fixed, labels } = textBoxes(elements)
  const rank = (d: ElementDefinition['data']) => (d.bridge ? 4 : d.risk ? 3 : d.onPath ? 2 : 1)
  const order = elements
    .filter((el) => labels.has(el.data.id!))
    .sort((a, b) => rank(b.data) - rank(a.data) || (b.data.width ?? 0) - (a.data.width ?? 0) || String(a.data.id).localeCompare(String(b.data.id)))
  for (const el of order) {
    const box = labels.get(el.data.id!)!
    if (fixed.some((t) => overlap(t, box))) el.data = { ...el.data, label: '', crowded: 1 }
    else fixed.push(box)
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
      selector: 'node[kind = "more"], node[kind = "fan"]',
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

    // --- the many small wallets that paid one wallet, drawn as one: it says how many and how much
    { selector: 'node[kind = "fan"]', style: { 'text-wrap': 'wrap', 'border-color': t.chain } },

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
    // A fan: many wallets and one wallet. Each line leaves its own wallet level, joins a trunk
    // between the columns and comes in along the wallet's own line, so none of them rises
    // through the text under a tile. All of them are that one wallet's, so the shared trunk
    // cannot be misread. The amount is written beside the wallet it belongs to.
    {
      selector: 'edge[fan]',
      style: { 'curve-style': 'taxi', 'taxi-direction': 'rightward', 'taxi-turn-min-distance': 8, 'font-size': 11 },
    },
    // The trunk stands nearer the one wallet than the many, clear of the amounts, which are
    // written beside the many: after the payers' amounts on the way in, before the payees' on
    // the way out (and short of where the Hop Rail's own amount is written).
    { selector: 'edge[fan = "in"]', style: { 'taxi-turn': `${FAN_TRUNK_IN}px` } },
    { selector: 'edge[fan = "in"][stub]', style: { 'source-label': 'data(stub)', 'source-text-offset': STUB_OFFSET } },
    // the group's tile is wider than a wallet's: its line turns sooner, onto the same trunk
    { selector: 'edge[fan = "in"][^stub]', style: { 'taxi-turn': `${FAN_TRUNK_IN - 21}px` } },
    { selector: 'edge[fan = "out"]', style: { 'taxi-turn': `${FAN_TRUNK_OUT}px` } },
    { selector: 'edge[fan = "out"][stub]', style: { 'target-label': 'data(stub)', 'target-text-offset': STUB_OFFSET } },
    // A bridge's payout joins two chains: a dotted line in the label colour (a bridge is a
    // named party), always captioned with the bridge and both chains.
    {
      selector: 'edge[bridge = 1]',
      style: { 'line-style': 'dashed', 'line-dash-pattern': [2, 4], 'line-color': t.verifiedText, 'target-arrow-color': t.verifiedText, 'text-wrap': 'wrap', 'font-size': 11 },
    },

    // --- context: other transfers of the wallets on the trail. Not the suspect wallet's money,
    // so it has a look of its own: the data colour, thin and dotted, no arrowhead fill, no
    // amount on the line, and a name only when asked for (hover, a click, a group's count).
    {
      selector: 'node[context = 1]',
      style: {
        shape: 'rectangle',
        width: CONTEXT_TILE,
        height: CONTEXT_TILE,
        'background-color': t.sunk,
        'background-image': 'none',
        'border-style': 'solid',
        'border-width': 1,
        'border-color': t.data,
        label: '',
        color: t.data,
        'font-size': 11,
        'text-margin-y': 3,
      },
    },
    { selector: 'node[context = 1].named, node[context = 1].hover', style: { label: 'data(name)', 'text-background-color': t.surface, 'text-background-opacity': 0.9, 'text-background-padding': '2px', 'z-index': 20 } },
    {
      selector: 'node[context = 1][kind = "ctxmore"]',
      style: { width: 30, height: 15, 'border-style': 'dashed', 'font-family': '"Public Sans", system-ui, sans-serif', 'font-size': 10, color: t.fg, 'text-valign': 'center', 'text-margin-y': 0, 'text-background-opacity': 0 },
    },
    {
      selector: 'edge[context = 1]',
      style: {
        width: 1,
        'curve-style': 'straight',
        'line-style': 'dashed',
        'line-dash-pattern': [1, 4],
        'line-cap': 'round',
        'line-color': t.data,
        'line-opacity': 0.75,
        'target-arrow-shape': 'vee',
        'target-arrow-color': t.data,
        'arrow-scale': 0.6,
        label: '',
      },
    },

    // --- looking at one wallet: its path stays, the rest steps back --------
    { selector: '.dim', style: { opacity: 0.2 } },
    // --- the replay: what has not moved yet is not drawn ---------------------
    { selector: '.ahead', style: { visibility: 'hidden' } },
    { selector: 'node.sel', style: { 'underlay-color': t.fg, 'underlay-opacity': 0.14, 'underlay-padding': 8, 'underlay-shape': 'rectangle' } },
    { selector: 'node.hover', style: { 'underlay-color': t.fg, 'underlay-opacity': 0.08, 'underlay-padding': 6, 'underlay-shape': 'rectangle' } },
  ] as StylesheetJsonBlock[]
}
