import { describe, expect, it } from 'vitest'
import {
  formatAmount,
  formatConfidence,
  formatConfidenceRange,
  formatDateTime,
  formatDuration,
  formatInr,
  formatPercent,
  formatUsd,
  truncateMiddle,
} from './format'

describe('truncateMiddle', () => {
  it('keeps six characters at each end, as the backend writes them', () => {
    expect(truncateMiddle('TCw8j3hdWgpB6S8gRYNrSwhfDVYnLLcoV5')).toBe('TCw8j3…LLcoV5')
  })
  it('leaves anything of 16 characters or fewer whole', () => {
    expect(truncateMiddle('0123456789abcdef')).toBe('0123456789abcdef')
  })
  it('takes other lengths', () => {
    expect(truncateMiddle('TCw8j3hdWgpB6S8gRYNrSwhfDVYnLLcoV5', 4, 4)).toBe('TCw8…coV5')
  })
})

describe('formatAmount (the rules of vaspfusion/explain/fmt.py)', () => {
  it.each([
    [48500, 'USDT', '48,500 USDT'],
    [252163.8, 'USDT', '252,163.80 USDT'],
    [2652.22, 'USDT', '2,652.22 USDT'],
    [0.364594, 'BTC', '0.364594 BTC'],
    [0.002428, 'ETH', '0.002428 ETH'],
    [0.5, 'BTC', '0.5 BTC'],
    [0, 'USDT', '0 USDT'],
  ])('%s %s → %s', (value, asset, text) => {
    expect(formatAmount(value, asset)).toBe(text)
  })
})

describe('money', () => {
  it('US dollars: whole sums without cents, others with two', () => {
    expect(formatUsd(48500)).toBe('$48,500')
    expect(formatUsd(990.5)).toBe('$990.50')
  })
  it('rupees in Indian grouping', () => {
    expect(formatInr(4050000)).toBe('₹40,50,000')
  })
})

describe('formatDuration', () => {
  it.each([
    [0, 'same block'],
    [36, '36 s'],
    [420, '7 min'],
    [960, '16 min'],
    [12600, '3 h 30 min'],
    [7200, '2 h'],
    [187200, '2 d 4 h'],
  ])('%s s → %s', (s, text) => {
    expect(formatDuration(s)).toBe(text)
  })
})

describe('formatConfidence', () => {
  it('two decimals', () => {
    expect(formatConfidence(0.91)).toBe('0.91')
    expect(formatConfidence(0.6)).toBe('0.60')
  })
  it('never prints certainty', () => {
    expect(formatConfidence(0.9993)).toBe('over 0.99')
    expect(formatConfidence(1)).toBe('over 0.99')
    expect(formatConfidence(0.001)).toBe('under 0.01')
  })
  it('a range, or that it is too narrow to show', () => {
    expect(formatConfidenceRange(0.84, 0.95)).toBe('range 0.84 to 0.95')
    expect(formatConfidenceRange(0.851, 0.853)).toBe('range narrower than 0.01')
  })
})

describe('formatPercent', () => {
  it.each([
    [0.85, '85%'],
    [0.004, 'under 1%'],
    [0.999, '99%'],
    [1, '100%'],
    [0, '0%'],
  ])('%s → %s', (share, text) => {
    expect(formatPercent(share)).toBe(text)
  })
})

describe('formatDateTime', () => {
  it('is UTC and says so', () => {
    expect(formatDateTime('2026-09-14T10:02:11Z')).toBe('14 Sep 2026, 10:02 UTC')
  })
})
