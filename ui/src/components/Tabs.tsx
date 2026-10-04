import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { cx } from '../lib/cx'
import { Frame } from './Panel'

export interface TabItem {
  id: string
  label: string
  /** How many records the tab holds; printed after its name. */
  count?: number
}

/** The records of a file: one tab stop, arrow keys move along them (and open the tab
 *  they land on), Home and End jump to the ends. The open tab is underlined in ink, as the
 *  header's current place is. */
export function Tabs({
  label,
  tabs,
  active,
  onChange,
  children,
}: {
  /** What the tabs are, for a screen reader: "Case records". */
  label: string
  tabs: TabItem[]
  active: string
  onChange: (id: string) => void
  /** The open tab's panel. */
  children: ReactNode
}) {
  const base = useId()
  const list = useRef<HTMLDivElement>(null)
  const index = Math.max(0, tabs.findIndex((t) => t.id === active))

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const to =
      e.key === 'ArrowRight' ? (index + 1) % tabs.length
      : e.key === 'ArrowLeft' ? (index - 1 + tabs.length) % tabs.length
      : e.key === 'Home' ? 0
      : e.key === 'End' ? tabs.length - 1
      : null
    if (to === null) return
    e.preventDefault()
    onChange(tabs[to].id)
    list.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[to]?.focus()
  }

  const open = tabs[index]
  return (
    <div>
      <div ref={list} role="tablist" aria-label={label} onKeyDown={onKeyDown} className="flex gap-0.5 overflow-x-auto border-b border-rule">
        {tabs.map((tab) => {
          const selected = tab.id === open.id
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              id={`${base}-tab-${tab.id}`}
              aria-selected={selected}
              aria-controls={`${base}-panel-${tab.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(tab.id)}
              className={cx(
                '-mb-px inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 text-base transition-colors duration-150',
                selected ? 'border-ink font-semibold text-ink' : 'border-transparent text-ink-dim hover:text-ink-soft',
              )}
            >
              {tab.label}
              {tab.count != null && ' '}
              {tab.count != null && (
                <span className={cx('tabular font-mono text-2xs', selected ? 'text-ink-soft' : 'text-ink-dim')}>{tab.count}</span>
              )}
            </button>
          )
        })}
      </div>
      <div
        role="tabpanel"
        id={`${base}-panel-${open.id}`}
        aria-labelledby={`${base}-tab-${open.id}`}
        tabIndex={0}
        className="panel border-t-0 p-4"
      >
        <Frame>{children}</Frame>
      </div>
    </div>
  )
}
