/** A FlowView as Cytoscape elements, and the stylesheet that draws them.
 *
 *  What the picture encodes (ui/DESIGN.md, "The fund-flow graph"):
 *    shape        the wallet's role (square-cornered: nothing in this language is a rounded token)
 *    border       the tier of its label, in the label colour (the same vocabulary as TierTag)
 *    chain colour the suspect wallet, unlabelled hops and the main path: on-chain facts
 *    fusion fill  a wallet of the exchange the case names, and nothing else
 *    danger fill  a sanctioned address or a mixer
 *    edge width   the amount; hairlines, dashed for money coming in */
import type { ElementDefinition, StylesheetJsonBlock } from 'cytoscape'
import { edgeWidth, nodeXY, type FlowNode, type FlowView, type Role } from '../lib/caseGraph'
import { formatAmount, truncateMiddle } from '../lib/format'

/** The role tokens the canvas needs, resolved to colours (a canvas cannot read CSS variables). */
export interface ThemeColors {
  fg: string
  muted: string
  surface: string
  sunk: string
  ruleStrong: string
  saffron: string
  chain: string
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

/** Shape and size per role. Every kind of labelled party has a shape of its own. */
export const ROLE_SHAPES: Record<Role, { shape: string; width: number; height: number }> = {
  suspect: { shape: 'rectangle', width: 30, height: 30 },
  intermediary: { shape: 'rectangle', width: 20, height: 20 },
  unknown: { shape: 'rectangle', width: 13, height: 13 },
  hub: { shape: 'hexagon', width: 34, height: 30 },
  exchange: { shape: 'cut-rectangle', width: 46, height: 28 },
  exchange_hot: { shape: 'cut-rectangle', width: 46, height: 28 },
  exchange_deposit: { shape: 'tag', width: 46, height: 28 },
  custodial_wallet: { shape: 'barrel', width: 42, height: 28 },
  swap_service: { shape: 'rhomboid', width: 46, height: 26 },
  bridge: { shape: 'diamond', width: 38, height: 38 },
  mixer: { shape: 'concave-hexagon', width: 40, height: 30 },
  sanctioned: { shape: 'octagon', width: 34, height: 34 },
}

/** What is written over a node: the owner a label names, or what the wallet is to the case. */
function captionOf(n: FlowNode): string | null {
  if (n.role === 'suspect') return 'Suspect'
  if (n.entity) return n.entity
  if (n.role === 'hub') return 'Busy wallet'
  return null
}

export function toElements(view: FlowView): ElementDefinition[] {
  const elements: ElementDefinition[] = []
  for (const n of view.nodes) {
    const position = nodeXY(n)
    elements.push({
      group: 'nodes',
      data: {
        id: n.id,
        kind: n.kind,
        role: n.role,
        tier: n.tier ?? 'none',
        named: n.named ? 1 : 0,
        onPath: n.onPath ? 1 : 0,
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
        position: { x: position.x, y: position.y - ROLE_SHAPES[n.role].height / 2 - 9 },
        classes: 'caption',
        selectable: false,
        grabbable: false,
      })
  }
  for (const e of view.edges)
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
        label: e.onPath || e.amount >= view.maxAmount * 0.1 ? formatAmount(e.amount, e.asset) : '',
      },
    })
  return elements
}

const svg = (body: string) => `data:image/svg+xml;utf8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">${body}</svg>`)}`
const stroke = (colour: string, d: string) =>
  `<path d="${d}" fill="none" stroke="${colour}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>`

/** A bar (no entry), two crossing arrows (mixed), two opposed arrows (carried across). */
const glyphs = (t: ThemeColors) => ({
  sanctioned: svg(`<rect x="5" y="10" width="14" height="4" rx="1" fill="${t.onSeal}"/>`),
  mixer: svg(stroke(t.onSeal, 'M4 8h2c6 0 6 8 12 8h2M4 16h2c6 0 6-8 12-8h2')),
  bridge: svg(stroke(t.fg, 'M5 9h13M15 6l3 3-3 3M19 15H6M9 12l-3 3 3 3')),
})

export function stylesheet(t: ThemeColors): StylesheetJsonBlock[] {
  const glyph = glyphs(t)
  const size = (role: Role) => ({ shape: ROLE_SHAPES[role].shape, width: ROLE_SHAPES[role].width, height: ROLE_SHAPES[role].height })
  const withGlyph = (image: string) => ({ 'background-image': image, 'background-width': '62%', 'background-height': '62%', 'background-clip': 'none' })

  // Cytoscape's own types want exact literals for shapes and styles; these are checked by
  // running the stylesheet through Cytoscape in flowStyle.test.ts.
  return [
    {
      selector: 'node',
      style: {
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

    // --- shape: the role --------------------------------------------------
    { selector: 'node[role = "suspect"]', style: { ...size('suspect'), 'background-color': t.chain, 'border-style': 'solid', 'border-width': 1, 'border-color': t.chain } },
    { selector: 'node[role = "intermediary"]', style: size('intermediary') },
    { selector: 'node[role = "unknown"]', style: size('unknown') },
    { selector: 'node[role = "hub"]', style: { ...size('hub'), 'background-color': t.sunk } },
    { selector: 'node[role = "exchange"]', style: size('exchange') },
    { selector: 'node[role = "exchange_hot"]', style: size('exchange_hot') },
    { selector: 'node[role = "exchange_deposit"]', style: size('exchange_deposit') },
    { selector: 'node[role = "custodial_wallet"]', style: size('custodial_wallet') },
    { selector: 'node[role = "swap_service"]', style: size('swap_service') },
    { selector: 'node[role = "bridge"]', style: { ...size('bridge'), ...withGlyph(glyph.bridge) } },
    { selector: 'node[role = "mixer"]', style: { ...size('mixer'), 'background-color': t.seal, 'border-color': t.fg, ...withGlyph(glyph.mixer) } },
    { selector: 'node[role = "sanctioned"]', style: { ...size('sanctioned'), 'background-color': t.seal, 'border-color': t.fg, ...withGlyph(glyph.sanctioned) } },

    // --- the exchange the case names: the one thing filled in the fusion colour ---
    { selector: 'node[named = 1]', style: { 'background-color': t.saffron } },

    // --- a group of one exchange's wallets: drawn as a stack --------------
    {
      selector: 'node[kind = "cluster"]',
      style: { width: 58, height: 34, ghost: 'yes', 'ghost-offset-x': 4, 'ghost-offset-y': -4, 'ghost-opacity': 0.45 },
    },

    // --- the rest of a hop in a large graph: one quiet node, not a wallet -----
    {
      selector: 'node[kind = "more"]',
      style: {
        shape: 'rectangle',
        width: 58,
        height: 26,
        'background-color': t.sunk,
        'border-style': 'dashed',
        'border-width': 1,
        'border-color': t.muted,
        'font-family': '"Public Sans", system-ui, sans-serif',
        color: t.fg,
      },
    },

    // --- the owner's name over a node -------------------------------------
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
    { selector: 'edge[inbound = 1]', style: { 'line-style': 'dashed', 'line-dash-pattern': [7, 5], 'line-opacity': 0.7 } },

    // --- looking at one wallet: its path stays, the rest steps back --------
    { selector: '.dim', style: { opacity: 0.2 } },
    { selector: 'node.sel', style: { 'underlay-color': t.fg, 'underlay-opacity': 0.14, 'underlay-padding': 8, 'underlay-shape': 'rectangle' } },
    { selector: 'node.hover', style: { 'underlay-color': t.fg, 'underlay-opacity': 0.08, 'underlay-padding': 6, 'underlay-shape': 'rectangle' } },
  ] as StylesheetJsonBlock[]
}
