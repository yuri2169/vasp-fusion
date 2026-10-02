/** How numbers, addresses and durations are written on screen. The rules follow
 *  vaspfusion/explain/fmt.py, so a figure reads the same in a meter as in the
 *  backend's own sentences. */

/** TVZpWt…KjUtzR. Anything of 16 characters or fewer is kept whole. */
export function truncateMiddle(s: string, head = 6, tail = 6): string {
  return s.length <= 16 || s.length <= head + tail + 1 ? s : `${s.slice(0, head)}…${s.slice(-tail)}`
}

const group = (n: number, min: number, max: number) =>
  n.toLocaleString('en-US', { minimumFractionDigits: min, maximumFractionDigits: max })

/** 48,500 · 252,163.80 · 0.002428. Whole sums have no decimals, other sums of 1 or
 *  more have two, and smaller ones up to six. */
export function formatNumber(value: number): string {
  if (Math.abs(value) >= 1) {
    const cents = Math.round(value * 100) / 100
    return Number.isInteger(cents) ? group(cents, 0, 0) : group(cents, 2, 2)
  }
  return group(value, 0, 6)
}

export function formatAmount(value: number, asset: string): string {
  return `${formatNumber(value)} ${asset}`
}

export function formatUsd(value: number): string {
  return `$${formatNumber(value)}`
}

/** ₹40,50,000: Indian grouping, no paise. */
export function formatInr(value: number): string {
  return `₹${Math.round(value).toLocaleString('en-IN')}`
}

/** For a ticket stub: 'same block', '36 s', '7 min', '3 h 30 min', '2 d 4 h'. */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s === 0) return 'same block'
  if (s < 60) return `${s} s`
  if (s < 3600) return `${Math.round(s / 60)} min`
  const two = (big: number, bigUnit: string, small: number, smallUnit: string) =>
    small ? `${big} ${bigUnit} ${small} ${smallUnit}` : `${big} ${bigUnit}`
  if (s < 86400) return two(Math.floor(s / 3600), 'h', Math.round((s % 3600) / 60), 'min')
  return two(Math.floor(s / 86400), 'd', Math.round((s % 86400) / 3600), 'h')
}

/** A probability to two decimals, never written as certain: 0.97, over 0.99, under 0.01. */
export function formatConfidence(p: number): string {
  if (p > 0.995) return 'over 0.99'
  if (p < 0.005) return 'under 0.01'
  return p.toFixed(2)
}

/** "range 0.84 to 0.95", or that it is too narrow to show at two decimals. */
export function formatConfidenceRange(low: number, high: number): string {
  if (high - low < 0.01) return 'range narrower than 0.01'
  return `range ${formatConfidence(low)} to ${formatConfidence(high)}`
}

/** Whole percent. Never rounds a part up to 100% or down to 0%. */
export function formatPercent(share: number): string {
  if (share <= 0) return '0%'
  if (share >= 1) return '100%'
  const whole = Math.round(share * 100)
  if (whole >= 100) return '99%'
  if (whole < 1) return 'under 1%'
  return `${whole}%`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const pad = (n: number) => String(n).padStart(2, '0')

/** 14 Sep 2026: chain times are UTC, and the screen says so wherever the hour is shown. */
export function formatDate(iso: string): string {
  const d = new Date(iso)
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return `${formatDate(iso)}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}
