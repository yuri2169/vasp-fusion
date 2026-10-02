import { CornerDownLeft, Search } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import type { Chain } from '../api/models'
import { useOpenCase } from '../api/queries'
import { Button } from '../components/Button'
import { ChainBadge } from '../components/ChainBadge'
import { inspectAddress } from '../lib/addresses'
import { CHAINS, EVM_TRACEABLE } from '../lib/chains'
import { cx } from '../lib/cx'

export const SEARCH_INPUT_ID = 'wallet-search'

const typingInField = (target: EventTarget | null) =>
  target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))

/** The way into every case: paste any wallet address. The chain is named while the officer
 *  is still typing, a typo is caught before any trace, and Enter opens the case.
 *  "/" puts the cursor here from anywhere; Escape clears it. */
export function GlobalSearch() {
  const [value, setValue] = useState('')
  const [evmChain, setEvmChain] = useState<Chain>('ethereum')
  const [failure, setFailure] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const hintId = useId()
  const navigate = useNavigate()
  const openCase = useOpenCase()

  const seen = inspectAddress(value)
  const isEvm = seen.state === 'valid' && CHAINS[seen.chain].family === 'evm'
  const chain: Chain | null = seen.state === 'valid' ? (isEvm ? evmChain : seen.chain) : null
  const canTrace = chain !== null && CHAINS[chain].traceable && !openCase.isPending

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || typingInField(e.target)) return
      e.preventDefault()
      inputRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const change = (next: string) => {
    setValue(next)
    setFailure(null)
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (seen.state !== 'valid' || !chain || !canTrace) return
    openCase.mutate(
      { address: seen.normalized, chain },
      {
        onSuccess: (opened) => {
          change('')
          navigate(`/cases/${encodeURIComponent(opened.id)}`)
        },
        onError: (error) =>
          setFailure(error instanceof ApiError ? error.detail : 'The case could not be opened. Try again.'),
      },
    )
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation()
      change('')
    }
  }

  // One line under the bar: the server's answer, else what is wrong with the address, else nothing.
  const hint: { tone: 'error' | 'note'; text: string } | null = failure
    ? { tone: 'error', text: failure }
    : seen.state === 'invalid'
      ? { tone: 'note', text: seen.reason }
      : chain && !CHAINS[chain].traceable
        ? { tone: 'note', text: CHAINS[chain].whyNot ?? `${CHAINS[chain].name} wallets cannot be traced yet.` }
        : null

  return (
    <form role="search" onSubmit={submit} className="relative flex min-w-0 flex-1 items-center gap-2">
      <label htmlFor={SEARCH_INPUT_ID} className="sr-only">
        Wallet address
      </label>
      <div
        className={cx(
          'flex h-10 min-w-0 max-w-[720px] flex-1 items-center gap-2 rounded border bg-surface pl-3 pr-2',
          'focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus',
          seen.state === 'invalid' || failure ? 'border-seal-text' : 'border-rule-strong',
        )}
      >
        <Search size={16} aria-hidden className="shrink-0 text-muted" />
        <input
          ref={inputRef}
          id={SEARCH_INPUT_ID}
          type="search"
          value={value}
          onChange={(e) => change(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Paste a wallet address to open a case"
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={seen.state === 'invalid' || undefined}
          aria-describedby={hint ? hintId : undefined}
          className="h-full min-w-0 flex-1 bg-transparent font-mono text-sm text-fg outline-none placeholder:font-sans placeholder:text-muted [&::-webkit-search-cancel-button]:hidden"
        />
        {seen.state === 'typing' && seen.guess && <ChainBadge chain={seen.guess} tentative />}
        {seen.state === 'invalid' && seen.guess && <ChainBadge chain={seen.guess} tentative />}
        {seen.state === 'valid' && !isEvm && <ChainBadge chain={seen.chain} />}
        {isEvm && (
          <select
            aria-label="Chain"
            value={evmChain}
            onChange={(e) => setEvmChain(e.target.value as Chain)}
            className="h-6 shrink-0 rounded-sm border border-rule-strong bg-surface px-1 font-mono text-xs font-medium text-fg"
          >
            {EVM_TRACEABLE.map((c) => (
              <option key={c} value={c}>
                {CHAINS[c].name}
              </option>
            ))}
          </select>
        )}
        {seen.state === 'empty' && (
          <kbd aria-hidden className="hidden h-5 shrink-0 items-center rounded-sm border border-rule px-1.5 font-mono text-xs text-muted sm:inline-flex">
            /
          </kbd>
        )}
      </div>
      <Button type="submit" disabled={!canTrace} icon={<CornerDownLeft size={14} aria-hidden />}>
        {openCase.isPending ? 'Opening…' : 'Trace wallet'}
      </Button>
      {hint && (
        <p
          id={hintId}
          role={hint.tone === 'error' ? 'alert' : 'status'}
          className={cx(
            'absolute left-0 top-full z-30 mt-1.5 max-w-[720px] rounded border bg-surface px-3 py-2 text-sm text-fg shadow-md',
            hint.tone === 'error' ? 'border-seal-text' : 'border-rule-strong',
          )}
        >
          {hint.text}
        </p>
      )}
    </form>
  )
}
