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

describe('brand colours', () => {
  it('are exactly the six in the brief', () => {
    expect(themes.brand).toMatchObject({
      ink: '#2B1622',
      paper: '#F5F4F8',
      saffron: '#E8772E',
      verified: '#1F7A74',
      seal: '#B3261E',
      slate: '#5B5566',
    })
  })

  it('stay the same in dark mode', () => {
    for (const name of ['ink', 'paper', 'saffron', 'verified', 'seal', 'slate'])
      expect(themes.dark[name]).toBe(themes.light[name])
  })

  it('give the dark theme the briefed surface and text', () => {
    expect(themes.dark.bg).toBe('#1A0F16')
    expect(themes.dark.fg).toBe('#EDE9F0')
  })
})

describe.each(['light', 'dark'] as const)('%s theme contrast (WCAG AA)', (name) => {
  const t = themes[name]
  const surfaces = ['bg', 'surface', 'surface-sunk']
  const texts = ['fg', 'fg-muted', 'saffron-text', 'verified-text', 'seal-text']

  it.each(texts.flatMap((fg) => surfaces.map((bg) => [fg, bg] as const)))('%s on %s is at least 4.5:1', (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['on-saffron', 'saffron'],
    ['on-verified', 'verified'],
    ['on-seal', 'seal'],
    ['saffron-text', 'saffron-wash'],
    ['verified-text', 'verified-wash'],
    ['seal-text', 'seal-wash'],
    ['fg-muted', 'slate-wash'],
    ['rail-fg', 'rail-bg'],
    ['rail-fg-muted', 'rail-bg'],
    ['rail-fg', 'rail-active'],
  ])('%s on %s is at least 4.5:1', (fg, bg) => {
    expect(contrast(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['rule-strong', 'bg'],
    ['rule-strong', 'surface'],
    ['focus', 'bg'],
    ['focus', 'surface'],
    ['rail-focus', 'rail-bg'],
  ])('%s against %s is at least 3:1 (non-text)', (a, b) => {
    expect(contrast(t[a], t[b])).toBeGreaterThanOrEqual(3)
  })
})

it('the dark block redefines every theme-dependent surface and text token', () => {
  const dark = css.slice(css.indexOf('/* dark */'))
  for (const name of ['bg', 'surface', 'surface-sunk', 'rule', 'rule-strong', 'fg', 'fg-muted', 'rail-bg', 'focus',
    'saffron-text', 'verified-text', 'seal-text', 'saffron-wash', 'verified-wash', 'seal-wash', 'slate-wash'])
    expect(dark, `--${name}`).toContain(`--${name}:`)
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
