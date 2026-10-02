import { OctagonAlert, RotateCcw } from 'lucide-react'
import { Button } from './Button'

/** Something failed. `detail` is the sentence that says what happened and what to do
 *  (the API's own `detail`, shown as it came). */
export function ErrorState({ title, detail, onRetry }: { title: string; detail: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-seal-text bg-seal-wash px-4 py-3.5">
      <OctagonAlert size={18} aria-hidden className="mt-0.5 shrink-0 text-seal-text" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="text-sm font-semibold text-fg">{title}</p>
        <p className="text-sm text-fg">{detail}</p>
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry} icon={<RotateCcw size={13} aria-hidden />}>
          Try again
        </Button>
      )}
    </div>
  )
}
