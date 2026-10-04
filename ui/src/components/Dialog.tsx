import { X } from 'lucide-react'
import { useId, useLayoutEffect, useRef, type MouseEvent, type ReactNode } from 'react'

/** A modal for a decision that should not be made in passing (withdraw a request, send it).
 *  It is the browser's own <dialog>: focus is kept inside it, Escape closes it, and focus
 *  goes back to the control that opened it. The title is the question; the buttons in
 *  `footer` name the action ("Withdraw request"), never "OK". */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  // Layout effect: close() must run while the element is still in the page, or the
  // browser cannot hand focus back to the opener.
  useLayoutEffect(() => {
    const dialog = ref.current
    if (!open || !dialog) return
    if (!dialog.open) dialog.showModal()
    return () => {
      if (dialog.open) dialog.close()
    }
  }, [open])

  if (!open) return null

  const onBackdrop = (e: MouseEvent<HTMLDialogElement>) => {
    if (e.target === e.currentTarget) onClose() // the click landed outside the panel
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={onBackdrop}
      className="w-[480px] max-w-[calc(100vw-32px)] border border-ink bg-surface p-0 text-ink"
    >
      <div className="flex items-start justify-between gap-4 px-5 pt-4">
        <h2 id={titleId} className="title text-lg">
          {title}
        </h2>
        <button
          type="button"
          aria-label="Close"
          onClick={onClose}
          className="-mr-1.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-muted hover:bg-sunk hover:text-fg"
        >
          <X size={16} aria-hidden />
        </button>
      </div>
      <div className="px-5 pb-5 pt-2 text-base text-fg">{children}</div>
      {footer && <div className="flex justify-end gap-2 border-t border-rule bg-sunk px-5 py-3">{footer}</div>}
    </dialog>
  )
}
