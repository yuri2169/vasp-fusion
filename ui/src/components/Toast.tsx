import { CircleCheck, Info, OctagonAlert, X } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { cx } from '../lib/cx'

export interface ToastInput {
  kind?: 'info' | 'success' | 'error'
  /** What happened, in the words of the action: "Request drafted", "Marked as sent". */
  title: string
  detail?: string
}

interface ToastItem extends ToastInput {
  id: number
}

const ToastContext = createContext<{ show: (t: ToastInput) => void } | null>(null)

/** How long a toast stays. An error stays until dismissed: it says what to do next. */
const STAY_MS = 6000

const ICONS = { info: Info, success: CircleCheck, error: OctagonAlert }
const ACCENT = { info: 'text-muted', success: 'text-verified-text', error: 'text-seal-text' }

function Toast({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const kind = toast.kind ?? 'info'
  const Icon = ICONS[kind]

  useEffect(() => {
    if (kind === 'error') return
    const t = window.setTimeout(onDismiss, STAY_MS)
    return () => window.clearTimeout(t)
  }, [kind, onDismiss])

  return (
    <div
      role={kind === 'error' ? 'alert' : 'status'}
      className={cx(
        'pointer-events-auto flex w-[360px] max-w-[calc(100vw-32px)] items-start gap-2.5 rounded border bg-surface px-3 py-2.5 shadow-md',
        kind === 'error' ? 'border-seal-text' : 'border-rule-strong',
      )}
    >
      <Icon size={16} aria-hidden className={cx('mt-0.5 shrink-0', ACCENT[kind])} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-fg">{toast.title}</p>
        {toast.detail && <p className="mt-0.5 text-sm text-muted">{toast.detail}</p>}
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDismiss}
        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-muted hover:bg-sunk hover:text-fg"
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  )
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const next = useRef(1)

  const show = useCallback((t: ToastInput) => {
    const id = next.current++
    setToasts((all) => [...all.slice(-3), { ...t, id }])
  }, [])
  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const value = useMemo(() => ({ show }), [show])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
        {toasts.map((t) => (
          <ToastRow key={t.id} toast={t} dismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

function ToastRow({ toast, dismiss }: { toast: ToastItem; dismiss: (id: number) => void }) {
  const onDismiss = useCallback(() => dismiss(toast.id), [dismiss, toast.id])
  return <Toast toast={toast} onDismiss={onDismiss} />
}

// eslint-disable-next-line react/only-export-components
export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast needs a <ToastProvider> above it')
  return ctx
}
