/** WCAG 2.x contrast maths, and a reader for the two token blocks in tokens.css. */

export function luminance(hex: string): number {
  const m = /^#([0-9a-f]{6})$/i.exec(hex.trim())
  if (!m) throw new Error(`not a 6-digit hex colour: ${hex}`)
  const n = parseInt(m[1], 16)
  const channel = (v: number) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * channel(n >> 16) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

export type TokenMap = Record<string, string>

/** The declarations of the block that follows `marker` (a comment in tokens.css). */
function block(css: string, marker: string): TokenMap {
  const at = css.indexOf(marker)
  if (at < 0) throw new Error(`tokens.css has no "${marker}" block`)
  const open = css.indexOf('{', at)
  const close = css.indexOf('}', open)
  const out: TokenMap = {}
  for (const m of css.slice(open + 1, close).matchAll(/--([a-z0-9-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim()
  return out
}

/** Follow var(--x) references until a literal is reached. */
function resolve(map: TokenMap): TokenMap {
  const out: TokenMap = {}
  const get = (name: string, depth = 0): string => {
    const raw = map[name]
    if (raw === undefined) throw new Error(`token --${name} is not defined`)
    const ref = /^var\(--([a-z0-9-]+)\)$/.exec(raw)
    if (!ref) return raw
    if (depth > 8) throw new Error(`token --${name} is circular`)
    return get(ref[1], depth + 1)
  }
  for (const name of Object.keys(map)) out[name] = get(name)
  return out
}

export function readThemes(css: string): { brand: TokenMap; light: TokenMap; dark: TokenMap } {
  const brand = block(css, '/* brand */')
  const light = block(css, '/* light */')
  const dark = block(css, '/* dark */')
  return { brand, light: resolve({ ...brand, ...light }), dark: resolve({ ...brand, ...light, ...dark }) }
}
