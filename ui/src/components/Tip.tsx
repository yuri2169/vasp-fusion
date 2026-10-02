import { useEffect, useId, useState, type FocusEvent, type MouseEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** A small card shown on hover and on keyboard focus (the whole of a shortened address,
 *  a hash, a counterfactual sentence). It is drawn in <body>, so a scrolling table or the
 *  Hop Rail never clips it. Escape closes it. */
export function useTip() {
  const id = useId()
  const [anchor, setAnchor] = useState<DOMRect | null>(null)

  useEffect(() => {
    if (!anchor) return
    const hide = () => setAnchor(null)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && hide()
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', hide, true)
    return () => {
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', hide, true)
    }
  }, [anchor])

  const show = (e: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => setAnchor(e.currentTarget.getBoundingClientRect())
  const hide = () => setAnchor(null)

  return {
    id,
    anchor,
    open: anchor !== null,
    /** Spread on the element the card belongs to. */
    bind: { onMouseEnter: show, onMouseLeave: hide, onFocus: show, onBlur: hide },
  }
}

const WIDTH = 380

export function Tip({ id, anchor, children }: { id: string; anchor: DOMRect | null; children: ReactNode }) {
  if (!anchor) return null
  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - WIDTH - 8))
  // Below the element, or above it when there is no room below.
  const above = anchor.bottom + 96 > window.innerHeight && anchor.top > 96
  return createPortal(
    <div
      role="tooltip"
      id={id}
      style={{
        position: 'fixed',
        left,
        maxWidth: `min(${WIDTH}px, calc(100vw - 16px))`,
        ...(above ? { bottom: window.innerHeight - anchor.top + 6 } : { top: anchor.bottom + 6 }),
      }}
      className="pointer-events-none z-50 rounded border border-rule-strong bg-surface px-2.5 py-2 text-xs text-fg shadow-md"
    >
      {children}
    </div>,
    document.body,
  )
}
