import type { ReactNode } from 'react'

/** The top of a screen: what this is, one line on what it is for, and its actions. */
export function PageHeader({
  title,
  eyebrow,
  children,
  meta,
  actions,
}: {
  title: ReactNode
  /** A small printed heading above the title, e.g. the case reference. */
  eyebrow?: ReactNode
  children?: ReactNode
  /** A line of facts about the thing itself (a case's complaint number, loss, date), under the title. */
  meta?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
        <h1 className="display text-ink">{title}</h1>
        {meta && <div className="mt-2 text-base text-ink-soft">{meta}</div>}
        {children && <p className="mt-2 max-w-[82ch] text-base text-ink-soft">{children}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
