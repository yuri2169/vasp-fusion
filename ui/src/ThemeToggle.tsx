/** Theme control.
 *
 * Three states, not two. "System" is the honest default - it means the app has
 * no opinion until the user expresses one - and it is a real state rather than a
 * hidden initial condition, so a user who has overridden their OS can get back
 * to following it. Two-state toggles silently become an override the first time
 * they are touched and then never track the system again.
 *
 * The choice is written to localStorage and applied to <html data-theme>. The
 * pre-paint script in index.html reads the same key, so there is no flash of the
 * wrong theme on load.
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';

export type Theme = 'system' | 'light' | 'dark';
const KEY = 'btcfusion.theme';

export function applyTheme(t: Theme) {
  const el = document.documentElement;
  if (t === 'system') el.removeAttribute('data-theme');
  else el.setAttribute('data-theme', t);
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => {
    // Light, not 'system', when nothing has been chosen. This is presented on
    // whatever machine is to hand, and following the OS meant a laptop in dark
    // mode opened the demo dark. The toggle still offers system and dark; only
    // the first-run default moved.
    try { return (localStorage.getItem(KEY) as Theme) || 'light'; } catch { return 'light'; }
  });

  useEffect(() => {
    applyTheme(theme);
    try { localStorage.setItem(KEY, theme); } catch { /* private mode: still applies for this session */ }
  }, [theme]);

  const OPTIONS: { key: Theme; label: string; icon: ReactNode }[] = [
    { key: 'light', label: 'Light theme', icon: (
      <><circle cx="7" cy="7" r="3" /><path d="M7 .5v2M7 11.5v2M.5 7h2M11.5 7h2M2.4 2.4l1.4 1.4M10.2 10.2l1.4 1.4M11.6 2.4l-1.4 1.4M3.8 10.2l-1.4 1.4" /></>
    ) },
    { key: 'system', label: 'Follow system theme', icon: (
      <><rect x="1" y="2" width="12" height="8" rx="1" /><path d="M5 12h4" /></>
    ) },
    { key: 'dark', label: 'Dark theme', icon: (
      <path d="M11.5 8.4A5 5 0 0 1 5.6 2.5a5 5 0 1 0 5.9 5.9z" />
    ) },
  ];

  return (
    <div role="radiogroup" aria-label="Colour theme"
         className="flex items-center border border-rule">
      {OPTIONS.map((o) => {
        const on = theme === o.key;
        return (
          <button key={o.key} role="radio" aria-checked={on} title={o.label}
                  onClick={() => setTheme(o.key)}
                  className={`w-7 h-7 inline-flex items-center justify-center cursor-pointer
                              transition-colors duration-150
                              ${on ? 'bg-surface-3 text-ink' : 'text-ink-dim hover:text-ink-soft'}`}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
                 stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"
                 aria-hidden focusable="false">
              {o.icon}
            </svg>
          </button>
        );
      })}
    </div>
  );
}
