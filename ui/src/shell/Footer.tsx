import { Link, useLocation } from 'react-router'
import type { Layer } from '../components/Panel'
import { RupeeBasis } from '../components/Rupees'

/** What each colour says about where a fact comes from (ui/DESIGN.md, "Colour"). */
// eslint-disable-next-line react/only-export-components
export const COLOUR_KEY: [Layer, string][] = [
  ['chain', 'on-chain fact'],
  ['network', 'label evidence'],
  ['fusion', 'attribution answer'],
  ['confirm', 'officer action'],
  ['danger', 'sanctioned or mixer'],
]

/** The status bar: what this is for, and the colour key. The palette is the one thing a
 *  viewer cannot infer, so it is spelled out where they first meet it, on the landing;
 *  everywhere after it is five swatches with the words in a tooltip (and for a screen reader). */
export function Footer() {
  const { pathname } = useLocation()
  const spelled = pathname === '/'
  return (
    <footer className="relative flex shrink-0 flex-wrap items-center gap-x-6 gap-y-1 border-t border-rule bg-surface px-4 py-2 print:hidden">
      <span className="text-2xs text-ink-dim">SIH 2026 · PS 26182 · MHA / I4C · Blockchain &amp; Cybersecurity</span>
      <Link to="/coverage" className="text-2xs text-ink-soft underline decoration-ink-dim underline-offset-2 hover:text-ink">
        Problem statement coverage
      </Link>
      <RupeeBasis className="text-2xs text-ink-dim" />
      <ul aria-label="Colour key" className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {COLOUR_KEY.map(([layer, words]) => (
          <li key={layer} title={words} className="flex items-center gap-2 text-2xs text-ink-dim">
            <span aria-hidden className="inline-block h-2 w-2" style={{ background: `var(--${layer})` }} />
            <span className={spelled ? '' : 'sr-only'}>{words}</span>
          </li>
        ))}
      </ul>
    </footer>
  )
}
