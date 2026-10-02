import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { cx } from '../lib/cx'

async function copy(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value)
  // Plain http on a LAN address has no clipboard API: fall back to a selection.
  const area = document.createElement('textarea')
  area.value = value
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  document.execCommand('copy')
  area.remove()
}

/** Copies `value` whole (an address or a hash is never copied in its short form). */
export function CopyButton({ value, label, className }: { value: string; label: string; className?: string }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = window.setTimeout(() => setCopied(false), 1600)
    return () => window.clearTimeout(t)
  }, [copied])

  return (
    <>
      <button
        type="button"
        aria-label={`Copy ${label}`}
        title={copied ? 'Copied' : `Copy ${label}`}
        onClick={() => copy(value).then(() => setCopied(true), () => setCopied(false))}
        className={cx(
          'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-muted hover:bg-sunk hover:text-fg',
          className,
        )}
      >
        {copied ? <Check size={14} aria-hidden className="text-verified-text" /> : <Copy size={14} aria-hidden />}
      </button>
      <span role="status" className="sr-only">
        {copied ? 'Copied' : ''}
      </span>
    </>
  )
}
