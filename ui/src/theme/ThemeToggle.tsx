import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { cx } from '../lib/cx'
import { getThemePref, setThemePref, type ThemePref } from './theme'

const OPTIONS: { key: ThemePref; name: string; Icon: LucideIcon }[] = [
  { key: 'light', name: 'Light theme', Icon: Sun },
  { key: 'system', name: 'Device theme', Icon: Monitor },
  { key: 'dark', name: 'Dark theme', Icon: Moon },
]

/** Three states, not two. "Device" is a real state, so an officer who has overridden the
 *  device's theme can go back to following it. The choice is kept by theme.ts and applied
 *  before first paint by index.html. */
export function ThemeToggle({ className }: { className?: string }) {
  const [pref, setPref] = useState<ThemePref>(getThemePref)
  return (
    <div role="radiogroup" aria-label="Colour theme" className={cx('flex shrink-0 items-center border border-rule', className)}>
      {OPTIONS.map(({ key, name, Icon }) => {
        const on = pref === key
        return (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={on}
            aria-label={name}
            title={name}
            onClick={() => {
              setThemePref(key)
              setPref(key)
            }}
            className={cx(
              'inline-flex h-7 w-7 items-center justify-center transition-colors duration-150',
              on ? 'bg-surface-3 text-ink' : 'text-ink-dim hover:text-ink-soft',
            )}
          >
            <Icon size={14} strokeWidth={1.6} aria-hidden />
          </button>
        )
      })}
    </div>
  )
}
