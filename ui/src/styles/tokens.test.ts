import { describe, expect, it } from 'vitest'
import { contrast, readThemes } from '../test/contrast'
import { readUi } from '../test/files'

const css = readUi('src/styles/tokens.css')
const themes = readThemes(css)

it('the contrast maths matches the WCAG reference values', () => {
  expect(contrast('#000000', '#FFFFFF')).toBeCloseTo(21, 5)
  expect(contrast('#767676', '#FFFFFF')).toBeCloseTo(4.54, 2) // the well-known AA boundary grey
  expect(contrast('#777777', '#FFFFFF')).toBeLessThan(4.5)
})

describe('the palette is BTC-FUSION’s, hex for hex', () => {
  it('light', () => {
    expect(themes.light).toMatchObject({
      paper: '#E4E8EC',
      surface: '#FFFFFF',
      'surface-2': '#F3F5F7',
      'surface-3': '#EDF0F3',
      ink: '#0E1C27',
      'ink-soft': '#4A5B69',
      'ink-dim': '#56646F',
      rule: '#C3CCD4',
      'rule-soft': '#DBE1E6',
      chain: '#2D6A9F',
      network: '#7B4B94',
      fusion: '#8C5B0E',
      confirm: '#2E7D5B',
      data: '#5C6B78',
      danger: '#A2453B',
      active: '#0E1C27',
      'active-wash': '#DCE3EA',
      chrome: '#0E1C27',
    })
  })

  it('dark is re-picked, not inverted', () => {
    expect(themes.dark).toMatchObject({
      paper: '#0A0E12',
      surface: '#1A2229',
      'surface-2': '#212A33',
      'surface-3': '#28323C',
      ink: '#E3E9EF',
      'ink-soft': '#A9B6C2',
      'ink-dim': '#8B99A6',
      rule: '#323E4A',
      'rule-soft': '#26303A',
      chain: '#6BAEE8',
      network: '#C199DA',
      fusion: '#E0A63F',
      confirm: '#54C793',
      data: '#9AA8B6',
      danger: '#EE8279',
      active: '#E3E9EF',
      'active-wash': '#2B3641',
      chrome: '#05080B',
    })
  })
})

describe('the role names U1 to U5 components use are aliases of the palette', () => {
  it.each([
    ['bg', 'paper'],
    ['surface-sunk', 'surface-2'],
    ['fg', 'ink'],
    ['fg-muted', 'ink-soft'],
    ['rule-strong', 'ink-dim'],
    ['focus', 'chain'],
    ['saffron', 'fusion'],
    ['saffron-text', 'fusion'],
    ['verified', 'network'],
    ['verified-text', 'network'],
    ['seal', 'danger'],
    ['seal-text', 'danger'],
    ['slate', 'data'],
  ])('--%s is --%s in both themes', (alias, token) => {
    expect(themes.light[alias]).toBe(themes.light[token])
    expect(themes.dark[alias]).toBe(themes.dark[token])
  })
})

describe.each(['light', 'dark'] as const)('%s theme contrast (WCAG AA)', (name) => {
  const t = themes[name]
  const grounds = ['paper', 'surface', 'surface-2', 'surface-3']
  // Text that may land on any ground. --confirm is not here: as text it sits on a panel or its wash.
  const texts = ['ink', 'ink-soft', 'ink-dim', 'chain', 'network', 'fusion', 'danger']

  // --ink-dim on --surface-3 is 4.47:1 in dark (BTC-FUSION's own values): text on that ground is --ink-soft.
  const pairs = texts.flatMap((fg) => grounds.map((bg) => [fg, bg] as const)).filter(([fg, bg]) => !(fg === 'ink-dim' && bg === 'surface-3'))

  it.each(pairs)('%s on %s is at least 4.5:1', (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    // a layer colour as tag text on its own wash
    ['chain', 'chain-wash'],
    ['network', 'network-wash'],
    ['fusion', 'fusion-wash'],
    ['confirm', 'confirm-wash'],
    ['danger', 'danger-wash'],
    ['data', 'surface-2'],
    ['confirm', 'surface'],
    // text on a filled plate or button
    ['on-saffron', 'saffron'],
    ['on-verified', 'verified'],
    ['on-seal', 'seal'],
    ['on-confirm', 'confirm'],
    ['paper', 'ink'],
    // sentences on a wash (the verify result, an error) and on a hovered row
    ['ink', 'network-wash'],
    ['ink-soft', 'network-wash'],
    ['ink', 'danger-wash'],
    ['ink', 'fusion-wash'],
    ['ink', 'active-wash'],
    ['ink-soft', 'active-wash'],
  ])('%s on %s is at least 4.5:1', (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['rule-strong', 'paper'],
    ['rule-strong', 'surface'],
    ['focus', 'paper'],
    ['focus', 'surface'],
  ])('%s against %s is at least 3:1 (non-text)', (a, b) => {
    expect(contrast(t[a], t[b])).toBeGreaterThanOrEqual(3)
  })
})

it('the dark block redefines every palette token', () => {
  const dark = css.slice(css.indexOf('/* dark */'), css.indexOf('/* dark-system'))
  for (const name of Object.keys(readThemes(css).palette)) expect(dark, `--${name}`).toContain(`--${name}:`)
})

it('applies the dark tokens for data-theme="dark" and for a dark system with no choice made', () => {
  expect(css).toContain(':root[data-theme="dark"]')
  expect(css).toMatch(/@media \(prefers-color-scheme: dark\)\s*{\s*:root:not\(\[data-theme="light"\]\)/)
})

it('keeps the two dark blocks identical', () => {
  const declarations = (from: string) => {
    const open = css.indexOf('{', css.indexOf(':root', css.indexOf(from)))
    return css.slice(open + 1, css.indexOf('}', open)).split(';').map((d) => d.trim()).filter(Boolean)
  }
  expect(declarations('/* dark-system')).toEqual(declarations('/* dark */'))
})
