/** The arithmetic of a chart, kept apart from its drawing so it can be tested. */

/** Maps a value in [d0, d1] to a position in [r0, r1]; values outside are clamped. */
export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0 || 1
  return (v) => r0 + ((Math.min(Math.max(v, Math.min(d0, d1)), Math.max(d0, d1)) - d0) / span) * (r1 - r0)
}

/** Round steps (1, 2, 2.5, 5 times a power of ten) from `min` to at least `max`: about `count` of them. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!(max > min)) return [min]
  const raw = (max - min) / count
  const power = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= raw) ?? raw
  const first = Math.floor(min / step) * step
  const ticks: number[] = []
  for (let v = first; v < max + step / 2; v += step) ticks.push(Number(v.toFixed(10)))
  return ticks
}

/** The lowest round value at or under `min`, so a zoomed axis starts on a tick and says where. */
export function floorTo(min: number, step: number): number {
  return Number((Math.floor(min / step + 1e-9) * step).toFixed(10))
}

/** Width of a bar, in percent of the longest: never so thin that a non-zero value disappears. */
export function barPercent(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0
  return Math.max(1, Math.min(100, (value / max) * 100))
}
