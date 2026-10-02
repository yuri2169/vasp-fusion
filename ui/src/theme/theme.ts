/** Theme: the officer's choice (light, dark) or the device's. tokens.css does the rest:
 *  `data-theme` on <html> wins; with no attribute, `prefers-color-scheme` decides.
 *  index.html applies the stored choice before first paint with the same key. */

export type ThemePref = 'system' | 'light' | 'dark'

const KEY = 'vaspfusion.theme'

export function getThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system' // storage blocked: follow the device
  }
}

export function applyTheme(pref: ThemePref = getThemePref()): void {
  const root = document.documentElement
  if (pref === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', pref)
}

export function setThemePref(pref: ThemePref): void {
  try {
    if (pref === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, pref)
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
