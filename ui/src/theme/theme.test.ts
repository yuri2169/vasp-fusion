import { describe, expect, it } from 'vitest'
import { setMedia } from '../test/setup'
import { applyTheme, getThemePref, resolvedTheme, setThemePref } from './theme'

describe('theme preference', () => {
  it('defaults to light, whatever the device asks for', () => {
    setMedia('(prefers-color-scheme: dark)')
    expect(getThemePref()).toBe('light')
    expect(resolvedTheme()).toBe('light')
    applyTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('dark sets data-theme and is remembered', () => {
    setThemePref('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('vaspfusion.theme')).toBe('dark')
    expect(getThemePref()).toBe('dark')
  })

  it('device removes the attribute and is remembered', () => {
    setThemePref('dark')
    setThemePref('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem('vaspfusion.theme')).toBe('system')
    expect(getThemePref()).toBe('system')
  })

  it('reads a junk stored value as light', () => {
    localStorage.setItem('vaspfusion.theme', 'purple')
    expect(getThemePref()).toBe('light')
    applyTheme()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('resolves device to what the device asks for', () => {
    setThemePref('system')
    expect(resolvedTheme()).toBe('light')
    setMedia('(prefers-color-scheme: dark)')
    expect(resolvedTheme()).toBe('dark')
    setThemePref('light')
    expect(resolvedTheme()).toBe('light')
  })
})
