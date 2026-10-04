import { createContext, useContext, useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { cx } from '../lib/cx'

/** Where a fact comes from. A colour is a claim about provenance (ui/DESIGN.md, "Colour"). */
export type Layer = 'chain' | 'network' | 'fusion' | 'confirm' | 'data' | 'danger'

const LAYER_VAR: Record<Layer, string> = {
  chain: 'var(--chain)',
  network: 'var(--network)',
  fusion: 'var(--fusion)',
  confirm: 'var(--confirm)',
  data: 'var(--data)',
  danger: 'var(--danger)',
}
const LAYER_WASH: Record<Layer, string> = {
  chain: 'var(--chain-wash)',
  network: 'var(--network-wash)',
  fusion: 'var(--fusion-wash)',
  confirm: 'var(--confirm-wash)',
  data: 'var(--surface-2)',
  danger: 'var(--danger-wash)',
}

// eslint-disable-next-line react/only-export-components
export const layerColor = (l: Layer) => LAYER_VAR[l]
// eslint-disable-next-line react/only-export-components
export const layerWash = (l: Layer) => LAYER_WASH[l]

/** True inside a region that already draws a frame. ONE FRAME BETWEEN A LEAF AND THE PAGE:
 *  a Panel inside a Panel renders `panel-sub` (filled, borderless), never a second border. */
const Framed = createContext(false)

/** Wrap a hand-drawn bordered region so Panels inside it know to go flat. */
export function Frame({ children }: { children: ReactNode }) {
  return <Framed.Provider value={true}>{children}</Framed.Provider>
}

/** A bordered region. `weight` is the compositional dial: exactly one `primary` per screen.
 *  `accent` names the layer the panel belongs to with a 2px rule on its left edge (a single
 *  edge is not a frame); say the layer in words inside the panel too, never by colour alone. */
export function Panel({
  children,
  accent,
  weight = 'standard',
  pad = true,
  className,
  style,
  ...rest
}: {
  children: ReactNode
  accent?: Layer
  weight?: 'primary' | 'standard' | 'sub'
  pad?: boolean
  className?: string
  style?: CSSProperties
  'aria-label'?: string
  'aria-labelledby'?: string
  id?: string
}) {
  const nested = useContext(Framed)
  const frame = nested || weight === 'sub' ? 'panel-sub' : weight === 'primary' ? 'panel-primary' : 'panel'
  return (
    <Framed.Provider value={true}>
      <section
        data-weight={nested ? 'sub' : weight}
        className={cx(frame, pad && 'p-4', className)}
        style={{ ...(accent ? { borderLeft: `2px solid ${LAYER_VAR[accent]}` } : {}), ...style }}
        {...rest}
      >
        {children}
      </section>
    </Framed.Provider>
  )
}

/** Section label, with something set against it on the right (a count, a link). */
export function Eyebrow({ children, layer, right, as: As = 'h2', id }: { children: ReactNode; layer?: Layer; right?: ReactNode; as?: 'h2' | 'h3' | 'p'; id?: string }) {
  return (
    <div className="mb-2 flex items-baseline justify-between gap-3">
      <As id={id} className="eyebrow" style={layer ? { color: LAYER_VAR[layer] } : undefined}>
        {children}
      </As>
      {right ? <span className="text-2xs text-ink-dim">{right}</span> : null}
    </div>
  )
}

/** A metric: its label above, the figure below. `lead` is the one headline figure of a screen. */
export function Stat({ label, value, sub, layer, size = 'md' }: { label: string; value: ReactNode; sub?: ReactNode; layer?: Layer; size?: 'md' | 'lead' }) {
  return (
    <div className="min-w-0">
      <div className="colhead mb-0.5 truncate">{label}</div>
      <div className={size === 'lead' ? 'figure truncate' : 'mono truncate text-md font-semibold leading-tight'} style={layer ? { color: LAYER_VAR[layer] } : undefined}>
        {value}
      </div>
      {sub ? <div className="text-2xs text-ink-dim">{sub}</div> : null}
    </div>
  )
}

/** A horizontal magnitude bar: the one place a filled rectangle means a number. It grows to
 *  its length, which is a value being measured. `delay` staggers a column of them. */
export function Bar({
  value,
  max = 1,
  layer = 'fusion',
  width = 150,
  height = 8,
  delay = 0,
  label,
}: {
  value: number
  max?: number
  layer?: Layer
  width?: number | '100%'
  height?: number
  delay?: number
  /** What the bar says, for a screen reader. Leave out when the number is printed beside it. */
  label?: string
}) {
  const share = Math.max(0, Math.min(1, Math.abs(value) / (max || 1)))
  return (
    <span className="inline-block bg-surface-3 align-middle" style={{ width, height }} role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : true}>
      <span className="anim-bar block h-full" style={{ width: `${share * 100}%`, background: LAYER_VAR[layer], animationDelay: `${delay}ms` }} />
    </span>
  )
}

/** Ref callback that makes an SVG path draw itself on mount, from its own measured length. */
// eslint-disable-next-line react/only-export-components
export function drawOnMount(delay = 0) {
  return (el: SVGGeometryElement | null) => {
    if (!el) return
    const len = el.getTotalLength?.()
    if (!len) return
    el.style.setProperty('--len', String(len))
    el.style.animationDelay = `${delay}ms`
    el.classList.add('anim-draw')
  }
}

/** A number that counts up to its value. Only for the one or two headline figures of a screen.
 *
 *  IT IS GUARANTEED TO LAND. requestAnimationFrame is suspended while a tab is hidden, so a
 *  counter started before a tab switch would strand partway, and a number frozen short of the
 *  truth is a false figure on screen. A timer force-sets the final value; under reduced motion
 *  the value is simply shown. */
export function Counter({ value, format, className, duration = 700 }: { value: number; format?: (n: number) => string; className?: string; duration?: number }) {
  const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const [moving, setShown] = useState(0)
  const shown = still ? value : moving
  useEffect(() => {
    if (still) return
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / duration)
      setShown(value * (1 - Math.pow(1 - k, 4)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    const settle = window.setTimeout(() => setShown(value), duration + 80)
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(settle)
    }
  }, [value, duration, still])
  return (
    <span className={className} aria-label={format ? format(value) : String(value)}>
      <span aria-hidden>{format ? format(shown) : Math.round(shown).toLocaleString('en-US')}</span>
    </span>
  )
}
