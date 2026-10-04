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
    <div className="flex flex-col items-start gap-3 rounded-md border border-dashed border-rule-strong px-6 py-8">
      {icon && <div className="text-muted">{icon}</div>}
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-fg">{title}</h2>
        {children && <p className="max-w-prose text-sm text-muted">{children}</p>}
      </div>
      {action}
    </div>
  )
}
