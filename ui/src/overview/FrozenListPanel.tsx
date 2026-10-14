import { Snowflake } from 'lucide-react'
import { useState } from 'react'
import type { FrozenCoverage } from '../api/models'
import { useFrozenSearch } from '../api/queries'
import { AddressChip } from '../components/AddressChip'
import { formatDate, formatDateTime } from '../lib/format'
import { Panel } from './parts'
import { chainName, count } from './words'

/** The issuer of USDT's freeze list, counted apart from the labels: a frozen address is a mark, not an owner. */
export function FrozenListPanel({ frozen }: { frozen: FrozenCoverage }) {
  const [q, setQ] = useState('')
  const [chain, setChain] = useState<'tron' | 'ethereum' | undefined>(undefined)
  const found = useFrozenSearch(q.trim(), chain)
  return (
    <Panel
      title="Frozen by the issuer of USDT"
      className="lg:col-span-12"
      note={
        <>
          {count(frozen.total)} addresses on USDT’s blacklist{frozen.cutoff ? ` as it stood on ${formatDateTime(frozen.cutoff)}` : ''}, read from the token contracts themselves (
          {Object.entries(frozen.by_chain)
            .map(([c, n]) => `${chainName(c)} ${count(n)}`)
            .join(', ')}
          ). Counted apart from the labels: a freeze names no owner.
        </>
      }
    >
      <p className="flex max-w-[100ch] items-start gap-2 text-base text-ink">
        <Snowflake size={15} aria-hidden className="mt-0.5 shrink-0 text-chain" />
        <span>{frozen.meaning}</span>
      </p>
      {frozen.check && <p className="max-w-[100ch] text-sm text-ink-soft">Checked: {frozen.check}.</p>}
      <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => e.preventDefault()} role="search" aria-label="Search the freeze list">
        <label className="flex flex-col gap-1 text-sm text-ink-soft">
          Address contains
          <input value={q} onChange={(e) => setQ(e.target.value)} className="h-8 w-72 border border-rule-strong bg-surface px-2 font-mono text-sm text-ink" spellCheck={false} />
        </label>
        <label className="flex flex-col gap-1 text-sm text-ink-soft">
          Chain
          <select value={chain ?? ''} onChange={(e) => setChain((e.target.value || undefined) as 'tron' | 'ethereum' | undefined)} className="h-8 border border-rule-strong bg-surface px-2 text-sm text-ink">
            <option value="">Both</option>
            <option value="tron">Tron</option>
            <option value="ethereum">Ethereum</option>
          </select>
        </label>
        {found.data && <span className="pb-1.5 text-sm text-ink-soft">{count(found.data.total)} match{found.data.total === 1 ? '' : 'es'}</span>}
      </form>
      {found.data && found.data.items.length > 0 && (
        <ul className="grid gap-x-6 sm:grid-cols-2 xl:grid-cols-3">
          {found.data.items.map((r) => (
            <li key={`${r.chain}:${r.address}`} className="flex items-center justify-between gap-3 border-b border-rule-soft py-1.5 text-sm">
              <AddressChip address={r.address} chain={r.chain as never} actions="copy" to={`/wallets/${r.chain}/${r.address}`} />
              <span className="whitespace-nowrap text-ink-soft">{chainName(r.chain)} · frozen {formatDate(r.frozen_at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}
