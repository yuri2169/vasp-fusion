import type { ReactNode } from 'react'

/** An empty screen invites the next action: it says what goes here and how to start. */
export function EmptyState({
  title,
  children,
  action,
  icon,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
  icon?: ReactNode
}) {
  return (
    <div className="flex flex-col items-start gap-3 border-l-2 border-data bg-surface-2 p-4">
      {icon && <div className="text-muted">{icon}</div>}
      <div className="flex flex-col gap-1">
        <h2 className="font-cond text-md font-semibold uppercase tracking-tight text-ink">{title}</h2>
        {children && <p className="max-w-[70ch] text-base text-ink-soft">{children}</p>}
      </div>
      {action}
    </div>
  )
}
