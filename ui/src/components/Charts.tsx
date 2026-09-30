/** Charts.
 *
 * Hand-drawn SVG rather than a charting library for the small ones. These are
 * histograms and scatter overlays with fixed domains; Recharts would add ~90KB
 * to an offline bundle to draw rectangles we can position exactly. The library
 * earns its place on the reliability diagram, where axes and tooltips are real work.
 *
 * Colour never carries meaning alone (WCAG 1.4.1): every series is also
 * distinguished by position, label, or shape, and each chart has a text summary.
 */
/* CHART TYPE NOTE: font sizes here are SVG user units inside a viewBox that is
   scaled to its container (measured 1.43x-2.09x), so the rendered size is the
   number below times that factor. They were 9, which rendered at 13-19px -
   larger than the 13px body text. Keep these small. */
import { drawOnMount } from '../ui';
import type { TxRow } from '../api';

/** Hour-of-day activity. The bar that peaks tells you when someone works. */
export function HourHistogram({ hist, offsetMin }: { hist: number[]; offsetMin: number }) {
  const max = Math.max(...hist, 1);
  const shift = Math.round(offsetMin / 60);
  return (
    <div>
      <div className="flex items-end gap-[3px] h-20 border-b border-rule">
        {hist.map((v, h) => {
          const localHour = (h + shift + 24) % 24;
          const working = localHour >= 8 && localHour <= 20;
          return (
            <div key={h} className="flex-1 group relative"
                 title={`${String(h).padStart(2, '0')}:00 UTC — ${v} transactions (local ${String(localHour).padStart(2, '0')}:00)`}>
              <div className="w-full transition-colors duration-150"
                   style={{
                     height: `${(v / max) * 76}px`,
                     background: working ? 'var(--network)' : 'var(--rule)',
                   }} />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between mono text-2xs text-ink-dim mt-1">
        <span>00 UTC</span><span>06</span><span>12</span><span>18</span><span>23</span>
      </div>
      <div className="mono text-2xs text-ink-dim mt-1">
        <span className="inline-block w-2 h-2 align-middle mr-1" style={{ background: 'var(--network)' }} />
        local working hours (08–20) · <span className="inline-block w-2 h-2 align-middle mx-1"
        style={{ background: 'var(--rule)' }} />outside
      </div>
    </div>
  );
}

/** Transaction timeline. Height encodes value, colour encodes tx-level score. */
export function TxTimeline({ txs }: { txs: TxRow[] }) {
  const pts = txs
    .map((t) => ({ ...t, ms: new Date(t.ts).getTime() }))
    .filter((t) => !Number.isNaN(t.ms))
    .sort((a, b) => a.ms - b.ms);
  if (pts.length === 0) return <div className="text-sm text-ink-soft">No transaction detail.</div>;

  const t0 = pts[0].ms, t1 = pts[pts.length - 1].ms || t0 + 1;
  const span = Math.max(1, t1 - t0);
  const maxV = Math.max(...pts.map((p) => p.value_out), 1);
  const W = 1000, H = 86;

  // Densest 6-hour window: the burst marker analysts actually look for.
  let burst = { start: 0, n: 0 };
  const win = 6 * 3600 * 1000;
  for (let i = 0; i < pts.length; i++) {
    const n = pts.filter((p) => p.ms >= pts[i].ms && p.ms < pts[i].ms + win).length;
    if (n > burst.n) burst = { start: pts[i].ms, n };
  }

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H + 16}`} className="w-full" style={{ height: 102 }}
           role="img" aria-label={`${pts.length} transactions over time`}>
        {burst.n > 2 && (
          <rect x={((burst.start - t0) / span) * W} y={0}
                width={Math.max(4, (win / span) * W)} height={H}
                fill="var(--fusion)" opacity={0.12} />
        )}
        <line x1={0} y1={H} x2={W} y2={H} stroke="var(--rule)" strokeWidth={1} />
        {pts.map((p, i) => {
          const x = ((p.ms - t0) / span) * W;
          const h = Math.max(2, (p.value_out / maxV) * (H - 6));
          const hot = p.tx_score >= 0.6;
          return (
            <rect key={i} x={x} y={H - h} width={3} height={h}
                  fill={hot ? 'var(--fusion)' : 'var(--data)'}
                  opacity={hot ? 0.95 : 0.5}>
              <title>{`${p.txid.slice(0, 16)}… — ₿${(p.value_out / 1e8).toFixed(4)} — score ${p.tx_score.toFixed(2)}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className="flex justify-between mono text-2xs text-ink-dim">
        <span>{new Date(t0).toISOString().slice(0, 10)}</span>
        {burst.n > 2 && (
          <span className="text-fusion">↑ densest window: {burst.n} tx in 6h</span>
        )}
        <span>{new Date(t1).toISOString().slice(0, 10)}</span>
      </div>
    </div>
  );
}

/** Reliability diagram — does 0.87 mean 87%? */
export function ReliabilityCurve({ points, ece }:
  { points: { predicted: number; observed: number; n: number }[]; ece: number }) {
  const W = 300, H = 210, P = 30;
  const sx = (v: number) => P + v * (W - P - 8);
  const sy = (v: number) => H - P - v * (H - P - 12);
  if (!points.length) return <div className="text-sm text-ink-soft">No calibration data.</div>;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label={`Reliability diagram, expected calibration error ${ece}`}>
        {/* perfect calibration */}
        <line x1={sx(0)} y1={sy(0)} x2={sx(1)} y2={sy(1)}
              stroke="var(--rule)" strokeWidth={1.2} strokeDasharray="4 3" />
        <polyline ref={drawOnMount(120)} fill="none" stroke="var(--fusion)" strokeWidth={2.2}
                  points={points.map((p) => `${sx(p.predicted)},${sy(p.observed)}`).join(' ')} />
        {points.map((p, i) => (
          <circle key={i} cx={sx(p.predicted)} cy={sy(p.observed)} r={3} fill="var(--fusion)">
            <title>{`predicted ${p.predicted.toFixed(2)} → observed ${p.observed.toFixed(2)} (n=${p.n})`}</title>
          </circle>
        ))}
        <line x1={P} y1={H - P} x2={W - 8} y2={H - P} stroke="var(--ink-soft)" strokeWidth={1} />
        <line x1={P} y1={12} x2={P} y2={H - P} stroke="var(--ink-soft)" strokeWidth={1} />
        <text x={P} y={H - 10} className="mono" fontSize="6.5" fill="var(--ink-dim)">0</text>
        <text x={W - 20} y={H - 10} className="mono" fontSize="6.5" fill="var(--ink-dim)">1</text>
        <text x={P + 40} y={H - 10} className="mono" fontSize="6.5" fill="var(--ink-dim)">predicted →</text>
        {/* Was x=6: the y-axis sits at user-x 24, so this label ran straight
            through the axis rule at every width tested. */}
        <text x={30} y={13} className="mono" fontSize="7" fill="var(--ink-dim)">observed</text>
      </svg>
      <div className="mono text-2xs text-ink-dim">
        dashed = perfect calibration · solid = measured ·{' '}
        <b style={{ color: ece < 0.05 ? 'var(--confirm)' : 'var(--fusion)' }}>ECE {ece.toFixed(3)}</b>
      </div>
    </div>
  );
}

/** Selective attribution: error rate among the answered cases as the engine is
 *  allowed to answer more of them, most-confident first. A flat, low curve means
 *  the confidence ordering is right; the gap to zero at full coverage is the
 *  cost of answering everything. Abstentions are not errors here - they are the
 *  coverage the policy gave up. */
export function RiskCoverageCurve({ curve, aurc, eaurc, target }: {
  curve: { coverage: number; risk: number }[]; aurc?: number; eaurc?: number; target?: number;
}) {
  const W = 300, H = 190, P = 30;
  const rmax = Math.max(0.05, target ?? 0, ...curve.map((p) => p.risk)) * 1.15;
  const sx = (v: number) => P + v * (W - P - 8);
  const sy = (v: number) => H - P - (v / rmax) * (H - P - 12);
  if (!curve.length) return <div className="text-sm text-ink-soft">No risk–coverage data.</div>;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label={`Attribution error rate against the share of entities answered; AURC ${aurc ?? 'not reported'}`}>
        {target !== undefined && (
          <>
            <line x1={sx(0)} y1={sy(target)} x2={sx(1)} y2={sy(target)}
                  stroke="var(--danger)" strokeWidth={1} strokeDasharray="4 3" />
            <text x={W - 8} y={sy(target) - 3} textAnchor="end" className="mono" fontSize="6.5"
                  fill="var(--danger)">target {target}</text>
          </>
        )}
        <polyline ref={drawOnMount(120)} fill="none" stroke="var(--network)" strokeWidth={2.2}
                  points={curve.map((p) => `${sx(p.coverage)},${sy(p.risk)}`).join(' ')} />
        <line x1={P} y1={H - P} x2={W - 8} y2={H - P} stroke="var(--ink-soft)" strokeWidth={1} />
        <line x1={P} y1={12} x2={P} y2={H - P} stroke="var(--ink-soft)" strokeWidth={1} />
        <text x={P} y={H - 10} className="mono" fontSize="6.5" fill="var(--ink-dim)">0</text>
        <text x={W - 20} y={H - 10} className="mono" fontSize="6.5" fill="var(--ink-dim)">1</text>
        <text x={P + 40} y={H - 10} className="mono" fontSize="6.5" fill="var(--ink-dim)">share answered →</text>
        <text x={P - 4} y={sy(rmax / 1.15) + 2} textAnchor="end" className="mono" fontSize="6.5"
              fill="var(--ink-dim)">{(rmax / 1.15).toFixed(2)}</text>
        <text x={30} y={9} className="mono" fontSize="7" fill="var(--ink-dim)">error among answered</text>
      </svg>
      <div className="mono text-2xs text-ink-dim">
        AURC <b className="text-ink">{aurc ?? '—'}</b> · excess over a perfect ordering{' '}
        <b className="text-ink">{eaurc ?? '—'}</b>
      </div>
    </div>
  );
}
