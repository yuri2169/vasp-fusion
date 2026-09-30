/** Attribution accuracy vs observation coverage — the honest-engineering chart.
 *
 *  Plotted rather than tabulated because the SHAPE is the argument: accuracy
 *  falls away as the collector sees less of the network, and a single number
 *  quoted at an unstated coverage would hide exactly that.
 *
 *  The random-choice line is drawn too. Whether it crosses above the measured
 *  accuracy at low coverage depends on the artefact: the fixed-threshold engine
 *  did (it mostly saw relays and picked confidently among them); the fitted
 *  policy abstains there instead. ModelPanel reads the crossing from the data
 *  rather than asserting it.
 */
import { drawOnMount } from '../ui';

type Row = {
  coverage: number; top1_accuracy: number; top3_accuracy: number;
  mrr: number; random_choice_baseline: number;
  // Definition v2 sweeps: the expected accuracy of guessing among the same
  // answered entities. The old baseline over-credits cases with no true candidate.
  random_choice_expected?: number;
};

export const chanceOf = (r: Row) => r.random_choice_expected ?? r.random_choice_baseline;

export function SensitivityCurve({ rows }: { rows: Row[] }) {
  if (!rows?.length) return null;
  const W = 440, H = 230, P = 36;
  const sx = (v: number) => P + v * (W - P - 12);
  const sy = (v: number) => H - P - v * (H - P - 16);
  const line = (f: (r: Row) => number) =>
    rows.map((r) => `${sx(r.coverage)},${sy(f(r))}`).join(' ');

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label="Attribution accuracy against observation coverage">
        {[0.25, 0.5, 0.75, 1].map((g) => (
          <line key={g} x1={P} y1={sy(g)} x2={W - 12} y2={sy(g)}
                stroke="var(--rule-soft)" strokeWidth={1} />
        ))}
        <polyline ref={drawOnMount(120)} fill="none" stroke="var(--data)" strokeWidth={1.4}
                  strokeDasharray="3 3" points={line(chanceOf)} />
        <polyline ref={drawOnMount(260)} fill="none" stroke="var(--chain)" strokeWidth={1.6}
                  strokeDasharray="5 3" points={line((r) => r.top3_accuracy)} />
        <polyline ref={drawOnMount(400)} fill="none" stroke="var(--network)" strokeWidth={2.4}
                  points={line((r) => r.top1_accuracy)} />
        {rows.map((r, i) => (
          <circle key={i} cx={sx(r.coverage)} cy={sy(r.top1_accuracy)} r={3}
                  fill="var(--network)">
            <title>{`coverage ${(r.coverage * 100).toFixed(0)}% → top-1 ${r.top1_accuracy.toFixed(3)} (chance ${chanceOf(r).toFixed(3)})`}</title>
          </circle>
        ))}
        <line x1={P} y1={H - P} x2={W - 12} y2={H - P} stroke="var(--ink-soft)" strokeWidth={1} />
        <line x1={P} y1={16} x2={P} y2={H - P} stroke="var(--ink-soft)" strokeWidth={1} />
        <text x={8} y={sy(1) + 3} fontSize="9" fill="var(--ink-dim)" fontFamily="Spline Sans Mono">1.0</text>
        <text x={8} y={sy(0) + 3} fontSize="9" fill="var(--ink-dim)" fontFamily="Spline Sans Mono">0.0</text>
        <text x={P} y={H - 12} fontSize="9" fill="var(--ink-dim)" fontFamily="Spline Sans Mono">0%</text>
        <text x={W - 40} y={H - 12} fontSize="9" fill="var(--ink-dim)" fontFamily="Spline Sans Mono">100%</text>
        <text x={P + 62} y={H - 12} fontSize="9" fill="var(--ink-dim)" fontFamily="Spline Sans Mono">
          announcements observed →
        </text>
      </svg>
      <div className="mono text-2xs text-ink-dim flex flex-wrap gap-x-3">
        <span><span className="inline-block w-3 h-0.5 align-middle mr-1"
                    style={{ background: 'var(--network)' }} />top-1</span>
        <span><span className="inline-block w-3 h-0.5 align-middle mr-1"
                    style={{ background: 'var(--chain)' }} />top-3</span>
        <span><span className="inline-block w-3 h-0.5 align-middle mr-1"
                    style={{ background: 'var(--data)' }} />random choice</span>
      </div>
    </div>
  );
}
