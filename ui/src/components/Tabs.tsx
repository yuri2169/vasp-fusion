import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { cx } from '../lib/cx'

export interface TabItem {
  id: string
  label: string
  /** How many records the tab holds; printed after its name. */
  count?: number
}

/** The index tabs of a file: one tab stop, arrow keys move along them (and open the tab
 *  they land on), Home and End jump to the ends. The open tab joins the sheet under it. */
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
      <div ref={list} role="tablist" aria-label={label} onKeyDown={onKeyDown} className="flex gap-1 overflow-x-auto px-px pt-px">
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
                'relative -mb-px inline-flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-t border border-b-0 px-3.5 text-sm font-medium',
                selected ? 'z-[1] border-rule bg-surface text-fg' : 'border-transparent text-muted hover:bg-sunk hover:text-fg',
              )}
            >
              {tab.label}
              {tab.count != null && ' '}
              {tab.count != null && (
                <span className={cx('tabular rounded-sm px-1 font-mono text-xs', selected ? 'bg-sunk text-fg' : 'text-muted')}>{tab.count}</span>
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
        className={cx('rounded-md border border-rule bg-surface p-5', index === 0 && 'rounded-tl-none')}
      >
        {children}
      </div>
    </div>
  )
}
