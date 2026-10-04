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
 *  "/" puts the cursor here from anywhere; Escape clears it.
 *  `bar` is the compact one in the header; `hero` is the landing's own, the largest control on it. */
export function GlobalSearch({ variant = 'bar' }: { variant?: 'bar' | 'hero' }) {
  const hero = variant === 'hero'
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
          // `watched`: the officer started this trace, so the case page extends the rail as the result lands.
          navigate(`/cases/${encodeURIComponent(opened.id)}`, { state: { watched: opened.status !== 'done' } })
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
    <form role="search" onSubmit={submit} className={cx('relative flex min-w-0 items-center gap-2', hero ? 'w-full' : 'flex-1 justify-end')}>
      <label htmlFor={SEARCH_INPUT_ID} className="sr-only">
        Wallet address
      </label>
      <div
        className={cx(
          'relative flex min-w-0 flex-1 items-center gap-2 border bg-surface pl-3 pr-2 transition-colors duration-150',
          'focus-within:outline focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-focus',
          hero ? 'h-12' : 'h-8 max-w-[440px]',
          seen.state === 'invalid' || failure ? 'border-danger' : hero ? 'border-ink' : 'border-rule hover:border-ink',
        )}
      >
        {/* Registration marks, as on a plate: the landing's box is the instrument's intake. */}
        {hero &&
          (['tl', 'tr', 'bl', 'br'] as const).map((c) => (
            <span
              key={c}
              aria-hidden
              className="pointer-events-none absolute h-2.5 w-2.5 border-ink"
              style={{
                top: c[0] === 't' ? -1 : undefined,
                bottom: c[0] === 'b' ? -1 : undefined,
                left: c[1] === 'l' ? -1 : undefined,
                right: c[1] === 'r' ? -1 : undefined,
                borderTopWidth: c[0] === 't' ? 2 : 0,
                borderBottomWidth: c[0] === 'b' ? 2 : 0,
                borderLeftWidth: c[1] === 'l' ? 2 : 0,
                borderRightWidth: c[1] === 'r' ? 2 : 0,
              }}
            />
          ))}
        <Search size={hero ? 16 : 14} aria-hidden className="shrink-0 text-ink-dim" />
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
          autoFocus={hero}
          aria-invalid={seen.state === 'invalid' || undefined}
          aria-describedby={hint ? hintId : undefined}
          className={cx(
            'h-full min-w-0 flex-1 bg-transparent font-mono text-ink outline-none placeholder:font-sans placeholder:text-ink-dim [&::-webkit-search-cancel-button]:hidden',
            hero ? 'text-md' : 'text-sm',
          )}
        />
        {seen.state === 'typing' && seen.guess && <ChainBadge chain={seen.guess} tentative />}
        {seen.state === 'invalid' && seen.guess && <ChainBadge chain={seen.guess} tentative />}
        {seen.state === 'valid' && !isEvm && <ChainBadge chain={seen.chain} />}
        {isEvm && (
          <select
            aria-label="Chain"
            value={evmChain}
            onChange={(e) => setEvmChain(e.target.value as Chain)}
            className="h-6 shrink-0 border border-rule bg-surface px-1 text-sm font-medium text-ink"
          >
            {EVM_TRACEABLE.map((c) => (
              <option key={c} value={c}>
                {CHAINS[c].name}
              </option>
            ))}
          </select>
        )}
        {seen.state === 'empty' && (
          <kbd aria-hidden className="hidden h-5 shrink-0 items-center border border-rule px-1.5 font-mono text-2xs text-ink-dim sm:inline-flex">
            /
          </kbd>
        )}
      </div>
      <Button
        type="submit"
        variant={hero ? 'primary' : 'secondary'}
        disabled={!canTrace}
        className={hero ? 'h-12 px-4 text-md' : 'w-8 px-0'}
        title={hero ? undefined : 'Trace wallet'}
        icon={<CornerDownLeft size={14} aria-hidden />}
      >
        <span className={hero ? undefined : 'sr-only'}>{openCase.isPending ? 'Opening…' : 'Trace wallet'}</span>
      </Button>
      {hint && (
        <p
          id={hintId}
          role={hint.tone === 'error' ? 'alert' : 'status'}
          className={cx(
            'absolute top-full z-30 mt-1.5 max-w-[720px] border bg-surface px-3 py-2 text-base text-ink',
            hero ? 'left-0' : 'right-0',
            hint.tone === 'error' ? 'border-danger' : 'border-ink',
          )}
        >
          {hint.text}
        </p>
      )}
    </form>
  )
}
