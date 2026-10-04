/** The icon inside each kind of tile on the fund-flow graph. The drawings are lucide's (the
 *  icon set the rest of the interface uses), read as path data so that the canvas, the PNG
 *  export and the legend all draw the same icon. */
import { __iconData as ban } from 'lucide-react/dist/esm/icons/ban.mjs'
import { __iconData as crosshair } from 'lucide-react/dist/esm/icons/crosshair.mjs'
import { __iconData as bridge } from 'lucide-react/dist/esm/icons/git-compare-arrows.mjs'
import { __iconData as inbox } from 'lucide-react/dist/esm/icons/inbox.mjs'
import { __iconData as landmark } from 'lucide-react/dist/esm/icons/landmark.mjs'
import { __iconData as repeat } from 'lucide-react/dist/esm/icons/repeat.mjs'
import { __iconData as shuffle } from 'lucide-react/dist/esm/icons/shuffle.mjs'
import { __iconData as vault } from 'lucide-react/dist/esm/icons/vault.mjs'
import { __iconData as wallet } from 'lucide-react/dist/esm/icons/wallet.mjs'
import { __iconData as waypoints } from 'lucide-react/dist/esm/icons/waypoints.mjs'
import type { Role } from '../lib/caseGraph'

export type IconNode = [string, Record<string, string | number>][]

/** A wallet that was not followed further has no icon: it is a small dashed tile. */
export const ROLE_ICONS: Record<Role, IconNode | null> = {
  suspect: crosshair.node,
  intermediary: wallet.node,
  unknown: null,
  hub: waypoints.node,
  exchange: landmark.node,
  exchange_hot: landmark.node,
  exchange_deposit: inbox.node,
  custodial_wallet: vault.node,
  swap_service: repeat.node,
  bridge: bridge.node,
  mixer: shuffle.node,
  sanctioned: ban.node,
}

/** The icon's shapes as SVG markup (no wrapper), for a data URI or an inline <svg>. */
export function iconMarkup(node: IconNode): string {
  return node
    .map(([tag, attrs]) => {
      const pairs = Object.entries(attrs)
        .filter(([k]) => k !== 'key')
        .map(([k, v]) => `${k}="${v}"`)
      return `<${tag} ${pairs.join(' ')}/>`
    })
    .join('')
}
