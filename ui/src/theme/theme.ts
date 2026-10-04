/** Theme: light unless the officer chose otherwise (light, dark, or follow the device).
 *  tokens.css does the rest: `data-theme` on <html> wins; with no attribute,
 *  `prefers-color-scheme` decides. index.html applies the same rule before first paint. */

export type ThemePref = 'system' | 'light' | 'dark'

const KEY = 'vaspfusion.theme'

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'system' || v === 'dark' ? v : 'light'
  } catch {
    return 'light' // storage blocked: the default
  }
}

export function applyTheme(pref: ThemePref = getThemePref()): void {
  const root = document.documentElement
  if (pref === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', pref)
}

export function setThemePref(pref: ThemePref): void {
  try {
    localStorage.setItem(KEY, pref)
  } catch {
    /* storage blocked: the choice lasts for this page only */
  }
  applyTheme(pref)
}

/** What is on screen right now. */
export function resolvedTheme(pref: ThemePref = getThemePref()): 'light' | 'dark' {
  if (pref !== 'system') return pref
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}
