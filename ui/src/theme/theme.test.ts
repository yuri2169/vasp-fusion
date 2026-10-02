import { describe, expect, it } from 'vitest'
import { setMedia } from '../test/setup'
import { applyTheme, getThemePref, resolvedTheme, setThemePref } from './theme'

describe('theme preference', () => {
  it('defaults to the system', () => {
    expect(getThemePref()).toBe('system')
  })

  it('dark sets data-theme and is remembered', () => {
    setThemePref('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(localStorage.getItem('vaspfusion.theme')).toBe('dark')
    expect(getThemePref()).toBe('dark')
  })

  it('system removes the attribute and the stored choice', () => {
    setThemePref('light')
    setThemePref('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem('vaspfusion.theme')).toBeNull()
  })

  it('reads a junk stored value as system', () => {
    localStorage.setItem('vaspfusion.theme', 'purple')
    expect(getThemePref()).toBe('system')
    applyTheme()
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })

  it('resolves system to what the device asks for', () => {
    expect(resolvedTheme()).toBe('light')
    setMedia('(prefers-color-scheme: dark)')
    expect(resolvedTheme()).toBe('dark')
    setThemePref('light')
    expect(resolvedTheme()).toBe('light')
  })
})
