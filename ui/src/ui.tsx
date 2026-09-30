/** Shared primitives.
 *
 * Every one of these is deliberately flat: hairline border, square corner, no
 * shadow. Panels sit ON the paper, they do not float above it.
 *
 * Restraint alone is not design, though - it was flat AND uniform, 30 panels in
 * one treatment with no focal point on any screen. The dial that fixes that is
 * `weight` on Panel, not more borders.
 */
import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode, CSSProperties } from 'react';

export type Layer = 'chain' | 'network' | 'fusion' | 'confirm' | 'data' | 'danger';

const LAYER_VAR: Record<Layer, string> = {
  chain: 'var(--chain)', network: 'var(--network)', fusion: 'var(--fusion)',
  confirm: 'var(--confirm)', data: 'var(--data)', danger: 'var(--danger)',
};
const LAYER_WASH: Record<Layer, string> = {
  chain: 'var(--chain-wash)', network: 'var(--network-wash)', fusion: 'var(--fusion-wash)',
  confirm: 'var(--confirm-wash)', data: 'var(--surface-2)', danger: 'var(--danger-wash)',
};

export const layerColor = (l: Layer) => LAYER_VAR[l];
export const layerWash = (l: Layer) => LAYER_WASH[l];

/** Section label. Mono, letterspaced, tinted by the data layer it introduces. */
export function Eyebrow({ children, layer, right }:
  { children: ReactNode; layer?: Layer; right?: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 mb-2">
      <span className="eyebrow" style={layer ? { color: LAYER_VAR[layer] } : undefined}>
        {children}
      </span>
      {right ? <span className="eyebrow">{right}</span> : null}
    </div>
  );
}

/** True inside a region that already draws a frame. Consumed by Panel.
 *
 * ONE FRAME BETWEEN A LEAF AND THE PAGE. Measured before this existed: every
 * leaf in the landing explainer sat inside 2-4 bordered ancestors - 94 leaves at
 * depth 2, 64 at depth 3, and none at all below 2. Boxes inside boxes inside
 * boxes is the single loudest dated signal in this interface, and it is the same
 * argument the panel weights already make: when every region is framed, the
 * frame says nothing.
 *
 * A nested Panel therefore renders `panel-sub` - filled, borderless - which is
 * exactly what that weight was defined for. Single-edge accent rules are NOT
 * frames and do not count; they carry a layer, not a boundary. */
const Framed = createContext(false);

/** Wrap any hand-rolled bordered region so Panels inside it know to go flat. */
export function Frame({ children }: { children: ReactNode }) {
  return <Framed.Provider value={true}>{children}</Framed.Provider>;
}

/** A bordered region.
 *
 * `accent` NAMES the evidence layer this panel belongs to. It used to do that
 * with a 4px coloured left rule and nothing else, which fails twice: it is the
 * only 4px border in the app (so it reads as decoration), and the layer was
 * carried by hue alone - invisible in greyscale, on a projector, or to a
 * colour-blind reader. The rule is now 2px and the layer is also spelled out in
 * words, so the information survives without the colour.
 *
 * `weight` is the compositional dial: exactly one `primary` per screen.
 */
export function Panel({ children, accent, weight = 'standard', className = '', pad = true, style }: {
  children: ReactNode; accent?: Layer; weight?: 'primary' | 'standard' | 'sub';
  className?: string; pad?: boolean; style?: CSSProperties;
}) {
  const nested = useContext(Framed);
  // Inside an existing frame, every weight collapses to the filled one. The
  // accent rule survives - it names a layer, it is not a boundary.
  const frame = nested ? 'panel-sub'
    : weight === 'primary' ? 'panel-primary'
    : weight === 'sub' ? 'panel-sub'
    : 'bg-surface border border-rule';
  return (
    <Framed.Provider value={true}>
      <section
        className={`${frame} ${pad ? 'p-4' : ''} ${className}`}
        style={{ ...(accent ? { borderLeft: `2px solid ${LAYER_VAR[accent]}` } : {}), ...style }}
      >
        {accent ? (
          <span className="colhead block mb-2" style={{ color: LAYER_VAR[accent] }}>
            {accent} layer
          </span>
        ) : null}
        {children}
      </section>
    </Framed.Provider>
  );
}

/** Inline metric: label above, figure below. Used across the receipt strip. */
export function Stat({ label, value, sub, layer, mono = true, size = 'md' }: {
  label: string; value: ReactNode; sub?: ReactNode; layer?: Layer; mono?: boolean;
  size?: 'md' | 'lead';
}) {
  return (
    <div className="min-w-0">
      <div className="colhead truncate mb-0.5">{label}</div>
      <div
        className={size === 'lead'
          ? 'figure truncate'
          : `${mono ? 'mono' : 'font-cond'} text-md font-semibold leading-tight truncate`}
        style={layer ? { color: LAYER_VAR[layer] } : undefined}
      >
        {value}
      </div>
      {sub ? <div className="text-2xs text-ink-dim truncate">{sub}</div> : null}
    </div>
  );
}

/** Horizontal magnitude bar. The one place a filled rectangle means a number.
 *
 * `delay` staggers a column of bars so they read as a set arriving in order
 * rather than as one block appearing. The growth is the point: a bar that grows
 * to its length shows a value being measured, which is the only kind of motion
 * this interface has any business doing. */
export function Bar({ value, max = 1, layer = 'fusion', width = 150, height = 8, negative, delay = 0 }: {
  value: number; max?: number; layer?: Layer; width?: number | '100%'; height?: number;
  negative?: boolean; delay?: number;
}) {
  const pct = Math.max(0, Math.min(1, Math.abs(value) / (max || 1)));
  return (
    <span
      className="inline-block align-middle bg-surface-3"
      style={{ width, height }}
      role="img"
      aria-label={`${value.toFixed(3)} of ${max}`}
    >
      <span
        className="block h-full anim-bar"
        style={{
          width: `${pct * 100}%`,
          background: negative ? 'var(--data)' : LAYER_VAR[layer],
          animationDelay: `${delay}ms`,
        }}
      />
    </span>
  );
}

/** Ref callback that makes an SVG polyline or path draw itself on mount.
 *
 * Sets --len from the element's own measured length, so the dash animation is
 * exact for any geometry rather than a guessed constant. A curve that draws is
 * the one piece of motion this product genuinely earns: it is what an
 * instrument does when it plots a trace. */
export function drawOnMount(delay = 0) {
  return (el: SVGGeometryElement | null) => {
    if (!el) return;
    const len = el.getTotalLength?.();
    if (!len) return;
    el.style.setProperty('--len', String(len));
    el.style.animationDelay = `${delay}ms`;
    el.classList.add('anim-draw');
  };
}

/** A number that counts up to its value on mount.
 *
 * Only for the one or two headline figures on a screen. A page where every digit
 * animates is a slot machine, not an instrument. */
export function Counter({ value, decimals = 0, format, className = '', duration = 700 }: {
  value: number; decimals?: number; format?: (n: number) => string;
  className?: string; duration?: number;
}) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(value); return; }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / duration);
      // Same exponential ease-out as the CSS, so counters and bars settle together.
      setShown(value * (1 - Math.pow(1 - k, 4)));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // GUARANTEE THE FINAL VALUE. requestAnimationFrame is suspended while the tab
    // is hidden, so a counter started just before a tab switch strands partway -
    // observed live at 0.004 for a metric whose real value is 0.0245. A number
    // frozen at 15% of the truth is not a cosmetic bug in a forensics tool, it is
    // a false figure on screen. Timers are throttled in background tabs but they
    // still fire, so this always lands.
    const settle = setTimeout(() => setShown(value), duration + 80);
    return () => { cancelAnimationFrame(raf); clearTimeout(settle); };
  }, [value, duration]);
  const text = format ? format(shown) : shown.toFixed(decimals);
  return <span className={className}>{text}</span>;
}

/** Small square-cornered tag. Never used decoratively — always carries a fact.
 *
 * Filled, not outlined. It carried a wash background AND a coloured border of
 * the same hue, which is the same claim made twice; the wash alone already makes
 * it a token. Dropping the border removed 36 frame-in-frame nestings on the
 * Model screen alone. Contrast is unaffected — the text was always measured
 * against the wash, which is why --fusion is #8C5B0E (5.39:1 on its own wash)
 * rather than the #B8791C that failed at 3.36:1. */
export function Tag({ children, layer = 'data', title }:
  { children: ReactNode; layer?: Layer; title?: string }) {
  return (
    <span
      title={title}
      className="mono text-2xs px-2 py-0.5 whitespace-nowrap"
      style={{ color: LAYER_VAR[layer], background: LAYER_WASH[layer] }}
    >
      {children}
    </span>
  );
}

export function Button({ children, onClick, variant = 'default', disabled, title, type }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; title?: string;
  variant?: 'default' | 'primary' | 'ghost' | 'danger'; type?: 'button' | 'submit';
}) {
  const base =
    'mono text-sm px-3 h-8 inline-flex items-center gap-2 border transition-colors ' +
    'duration-150 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer select-none';
  const v = {
    default: 'bg-surface border-ink text-ink hover:bg-surface-3',
    primary: 'border-transparent hover:opacity-90',
    ghost: 'bg-transparent border-rule text-ink-soft hover:bg-surface-3 hover:text-ink',
    danger: 'bg-surface border-danger text-danger hover:bg-danger-wash',
  }[variant];
  return (
    <button
      type={type || 'button'} onClick={onClick} disabled={disabled} title={title}
      className={`${base} ${v}`}
      style={variant === 'primary'
        ? { background: 'var(--confirm)', color: 'var(--surface)' } : undefined}
    >
      {children}
    </button>
  );
}

/** Filter chip. Pressed state is a real aria-pressed toggle, not a colour trick. */
export function Chip({ active, onClick, children, layer = 'fusion', disabled }: {
  active?: boolean; onClick?: () => void; children: ReactNode; layer?: Layer;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick} aria-pressed={!!active} disabled={disabled}
      className="text-sm px-3 h-7 border transition-colors duration-150 whitespace-nowrap
                 cursor-pointer disabled:opacity-40 disabled:cursor-default"
      style={active
        ? { color: LAYER_VAR[layer], borderColor: LAYER_VAR[layer], background: LAYER_WASH[layer] }
        : { color: 'var(--ink-soft)', borderColor: 'var(--rule)', background: 'var(--surface)' }}
    >
      {children}
    </button>
  );
}

/** Empty / loading / error state. Always says what to do next. */
export function Notice({ title, children, layer = 'data' }:
  { title: string; children?: ReactNode; layer?: Layer }) {
  return (
    <div className="bg-surface-2 p-4" style={{ borderLeft: `2px solid ${LAYER_VAR[layer]}` }}>
      <div className="font-cond font-semibold uppercase text-md tracking-tight">{title}</div>
      {children ? <div className="text-sm text-ink-soft mt-1 max-w-[70ch]">{children}</div> : null}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-soft mono">
      <span className="inline-block w-2 h-2 bg-fusion blink" />
      {label}
    </div>
  );
}

/* --- Icons. Inline SVG, stroke-only, sized to the type. Never emoji. --------- */
type IcoProps = { className?: string };
const ico = (d: ReactNode) => ({ className = 'w-3.5 h-3.5' }: IcoProps) => (
  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4"
       strokeLinecap="square" className={className} aria-hidden="true">{d}</svg>
);

export const IconBack = ico(<path d="M10 3 5 8l5 5" />);
export const IconCheck = ico(<path d="M3 8.5 6.5 12 13 4" />);
export const IconX = ico(<><path d="M4 4l8 8" /><path d="M12 4l-8 8" /></>);
export const IconExport = ico(<><path d="M8 11V2" /><path d="M5 5l3-3 3 3" /><path d="M2.5 10v4h11v-4" /></>);
export const IconUpload = ico(<><path d="M8 2v9" /><path d="M5 5l3-3 3 3" /><path d="M2.5 13h11" /></>);
export const IconFilter = ico(<path d="M2 3h12l-4.5 5.5V14L6.5 12V8.5z" />);
export const IconGraph = ico(<><circle cx="4" cy="12" r="1.8" /><circle cx="12" cy="4" r="1.8" /><circle cx="12" cy="12" r="1.8" /><path d="M5.4 10.8 10.6 5.4M6 12h4" /></>);
