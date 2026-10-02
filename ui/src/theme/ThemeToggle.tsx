import { Monitor, Moon, Sun } from 'lucide-react'
import { useState } from 'react'
import { getThemePref, setThemePref, type ThemePref } from './theme'

const ORDER: ThemePref[] = ['system', 'light', 'dark']
const LOOK = {
  system: { Icon: Monitor, name: 'Device theme' },
  light: { Icon: Sun, name: 'Light theme' },
  dark: { Icon: Moon, name: 'Dark theme' },
}

/** One button that steps through device → light → dark. It says which is on, and what a click does. */
export function ThemeToggle({ className, showLabel = true }: { className?: string; showLabel?: boolean }) {
  const [pref, setPref] = useState<ThemePref>(getThemePref)
  const next = ORDER[(ORDER.indexOf(pref) + 1) % ORDER.length]
  const { Icon, name } = LOOK[pref]
  return (
    <button
      type="button"
      title={`${name}. Switch to ${LOOK[next].name.toLowerCase()}`}
      aria-label={`${name}. Switch to ${LOOK[next].name.toLowerCase()}`}
      onClick={() => {
        setThemePref(next)
        setPref(next)
      }}
      className={className}
    >
      <Icon size={16} aria-hidden className="shrink-0" />
      {showLabel && <span className="truncate">{name}</span>}
    </button>
  )
}
