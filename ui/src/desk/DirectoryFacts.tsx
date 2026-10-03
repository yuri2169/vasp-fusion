import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import type { DirectorySource, VaspDirectoryEntry } from '../api/models'
import { CopyButton } from '../components/CopyButton'
import { formatDate } from '../lib/format'
import { registrationWords } from './status'

const KIND_WORDS: Record<DirectorySource['kind'], string> = {
  official: 'Official document',
  exchange: "The exchange's own statement",
  news: 'News report',
}

const NoSource = () => <span className="text-muted">No source found</span>

function SourceLine({ source }: { source: DirectorySource }) {
  return (
    <span className="block text-xs text-muted">
      {KIND_WORDS[source.kind]}:{' '}
      <a href={source.url} target="_blank" rel="noreferrer" className="underline decoration-rule-strong underline-offset-2 hover:text-fg">
        {source.title}
        <ExternalLink size={11} aria-hidden className="ml-1 inline align-baseline" />
      </a>
      {source.published && `, published ${formatDate(source.published)}`}
    </span>
  )
}

function Fact({ name, sources, children }: { name: string; sources: DirectorySource[]; children: ReactNode }) {
  return (
    <div className="grid gap-x-4 gap-y-1 border-b border-rule py-3 last:border-b-0 sm:grid-cols-[190px_1fr]">
      <dt className="eyebrow pt-0.5">{name}</dt>
      <dd className="min-w-0 text-sm text-fg">
        {children}
        {sources.map((s, i) => (
          <SourceLine key={s.url + i} source={s} />
        ))}
      </dd>
    </div>
  )
}

function Channel({ value }: { value: string }) {
  const isUrl = /^https?:\/\//.test(value)
  return (
    <span className="inline-flex max-w-full items-center gap-1.5">
      {isUrl ? (
        <a href={value} target="_blank" rel="noreferrer" className="break-all font-mono text-sm underline decoration-rule-strong underline-offset-2">
          {value}
        </a>
      ) : (
        <span className="break-all font-mono text-sm">{value}</span>
      )}
      <CopyButton value={value} label="channel" />
    </span>
  )
}

/** What is on file about an exchange. Every fact shown has a source, named under it;
 *  a blank is said to be a blank ("No source found"), because it does not mean "no". */
export function DirectoryFacts({ directory }: { directory: VaspDirectoryEntry }) {
  const of = (field: string) => (directory.sources ?? []).filter((s) => s.field === field)
  const selfReported = directory.fiu_ind_registered === true && of('fiu_ind_registered').some((s) => s.kind === 'exchange')
  const notes = directory.notes ?? []

  return (
    <dl className="rounded-md border border-rule bg-surface px-4">
      <Fact name="Legal name" sources={of('legal_name')}>
        {directory.legal_name ?? <NoSource />}
      </Fact>
      <Fact name="FIU-IND registration" sources={of('fiu_ind_registered')}>
        <span className={directory.fiu_ind_registered == null ? 'text-muted' : 'font-medium'}>{registrationWords(directory)}</span>
        {directory.fiu_ind_registered == null && (
          <span className="block text-xs text-muted">A blank is not a "no": check whether it is a reporting entity before relying on a reply.</span>
        )}
        {selfReported && <span className="block text-xs text-muted">Known only from the exchange's own statement, not from an FIU-IND list.</span>}
      </Fact>
      <Fact name="Jurisdiction" sources={of('jurisdiction')}>
        {directory.jurisdiction ?? <NoSource />}
      </Fact>
      <Fact name="Law-enforcement channel" sources={of('le_request_channel')}>
        {directory.le_request_channel ? <Channel value={directory.le_request_channel} /> : <NoSource />}
      </Fact>
      {notes.length > 0 && (
        <Fact name="Notes on file" sources={of('notes')}>
          <ul className="mb-1 flex flex-col gap-1.5">
            {notes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        </Fact>
      )}
    </dl>
  )
}
