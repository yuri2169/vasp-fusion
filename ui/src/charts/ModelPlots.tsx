import type { ModelInfo } from '../api/models'
import { formatConfidence, formatPercent } from '../lib/format'
import { share } from '../overview/words'
import { ChartTable, PlotFrame, PlotLine, PlotPoint, PlotReference } from './Plot'
import { floorTo, linear } from './scale'

type Bin = ModelInfo['reliability'][number]
type CoveragePoint = ModelInfo['risk_coverage'][number]

const two = (v: number) => v.toFixed(2)
const count = (n: number) => n.toLocaleString('en-US')

/** Calibration: of the addresses the model gave about p, what share were deposit addresses?
 *  On the dashed diagonal the two agree. Under the plot, how many addresses each point stands for:
 *  a point far from the diagonal that stands for three addresses says little. */
export function ReliabilityPlot({ bins }: { bins: Bin[] }) {
  const shown = bins.filter((b) => b.count > 0)
  const px = (b: Bin) => b.predicted ?? b.bin_mid
  const most = Math.max(...shown.map((b) => b.count), 1)
  return (
    <div>
      <PlotFrame
        label={`Reliability plot: ${shown.length} groups of addresses, the predicted probability against the share that were deposit addresses`}
        xDomain={[0, 1]}
        yDomain={[0, 1]}
        xTicks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
        yTicks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
        xTitle="Probability the model gave"
        yTitle="Share that were deposit addresses"
        xFormat={two}
        yFormat={two}
      >
        {(f) => (
          <>
            <PlotReference from={[f.x(0), f.y(0)]} to={[f.x(1), f.y(1)]} name="given = observed" at={0.3} anchor="start" />
            <PlotLine points={shown.map((b) => [f.x(px(b)), f.y(b.observed)])} />
            {shown.map((b) => (
              <PlotPoint
                key={b.bin_mid}
                cx={f.x(px(b))}
                cy={f.y(b.observed)}
                name={`Predicted ${formatConfidence(px(b))}, observed ${formatConfidence(b.observed)}, ${count(b.count)} addresses`}
              >
                <span className="block font-medium">{count(b.count)} addresses</span>
                <span className="tabular mt-0.5 block font-mono text-muted">
                  predicted {formatConfidence(px(b))} · observed {formatConfidence(b.observed)}
                </span>
              </PlotPoint>
            ))}
          </>
        )}
      </PlotFrame>
      <CountStrip bins={shown} most={most} />
      <ChartTable
        caption="Reliability, per group of addresses"
        head={['Probability given', 'Share observed', 'Addresses']}
        rows={shown.map((b) => [formatConfidence(px(b)), formatConfidence(b.observed), count(b.count)])}
      />
    </div>
  )
}

/** How many addresses stand behind each point, on the plot's own x axis. */
function CountStrip({ bins, most }: { bins: Bin[]; most: number }) {
  const x = linear(0, 1, 52, 502)
  const h = linear(0, most, 0, 40)
  return (
    <svg viewBox="0 0 520 78" role="img" aria-label="Addresses in each group" className="tabular block w-full" style={{ maxWidth: 520 }}>
      <text x={52} y={10} fontSize={12} fill="var(--fg-muted)">
        Addresses in each group
      </text>
      {bins.map((b) => {
        const cx = x(b.predicted ?? b.bin_mid)
        const height = Math.max(1.5, h(b.count))
        return (
          <g key={b.bin_mid}>
            <path d={`M${cx - 5} 62 V${62 - height} h10 V62 Z`} fill="var(--fusion)" />
            <text x={cx} y={75} textAnchor="middle" fontSize={12} fill="var(--fg-muted)">
              {b.count >= 1000 ? `${(b.count / 1000).toFixed(1)}k` : b.count}
            </text>
          </g>
        )
      })}
      <line x1={52} x2={502} y1={62.5} y2={62.5} stroke="var(--rule)" strokeWidth={1} />
    </svg>
  )
}

/** Accuracy when answering against coverage: how often the answers are right when only the
 *  surest `coverage` share of the cases is answered. The y axis is zoomed and says where it starts. */
export function CoveragePlot({
  points,
  xTitle,
  yTitle,
  caption,
  reference,
}: {
  points: CoveragePoint[]
  xTitle: string
  yTitle: string
  caption: string
  /** A level to read the line against, e.g. what one rule alone scores. */
  reference?: { value: number; name: string }
}) {
  const lowest = Math.min(...points.map((p) => p.accuracy), reference?.value ?? 1)
  const y0 = lowest >= 0.9 ? Math.min(0.9, floorTo(lowest, 0.02)) : floorTo(lowest, 0.1)
  // Enough points to see the shape; every one of them is in the table.
  const step = Math.ceil(points.length / 14)
  const marked = points.filter((_, i) => i % step === 0 || i === points.length - 1)
  return (
    <div>
      <PlotFrame
        label={caption}
        height={280}
        xDomain={[0, 1]}
        yDomain={[y0, 1]}
        xTitle={xTitle}
        yTitle={yTitle}
        xFormat={(v) => formatPercent(v)}
        yFormat={(v) => `${Math.round(v * 100)}%`}
      >
        {(f) => (
          <>
            {reference && <PlotReference from={[f.x(0), f.y(reference.value)]} to={[f.x(1), f.y(reference.value)]} name={reference.name} />}
            <PlotLine points={points.map((p) => [f.x(p.coverage), f.y(p.accuracy)])} />
            {marked.map((p) => (
              <PlotPoint key={p.coverage} cx={f.x(p.coverage)} cy={f.y(p.accuracy)} name={`Answering ${share(p.coverage)}: ${share(p.accuracy)} right`}>
                <span className="block font-medium">Answering the surest {share(p.coverage)}</span>
                <span className="tabular mt-0.5 block font-mono text-muted">{share(p.accuracy)} of those answers are right</span>
              </PlotPoint>
            ))}
          </>
        )}
      </PlotFrame>
      {y0 > 0 && <p className="text-sm text-muted">The vertical axis starts at {Math.round(y0 * 100)}%, not at zero.</p>}
      <ChartTable caption={caption} head={['Share answered', 'Right when answering']} rows={points.map((p) => [share(p.coverage), share(p.accuracy)])} />
    </div>
  )
}
