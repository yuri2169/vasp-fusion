import { OctagonAlert, RotateCcw } from 'lucide-react'
import { Button } from './Button'

/** Something failed. `detail` is the sentence that says what happened and what to do
 *  (the API's own `detail`, shown as it came). */
export function ErrorState({ title, detail, onRetry }: { title: string; detail: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 border-l-2 border-danger bg-danger-wash p-4">
      <OctagonAlert size={16} aria-hidden className="mt-0.5 shrink-0 text-danger" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="font-cond text-md font-semibold uppercase tracking-tight text-ink">{title}</p>
        <p className="text-base text-fg">{detail}</p>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry} icon={<RotateCcw size={13} aria-hidden />}>
          Try again
        </Button>
      )}
    </div>
  )
}
