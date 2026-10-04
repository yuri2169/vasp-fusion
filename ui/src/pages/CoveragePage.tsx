import { CircleCheck, CircleDashed, CircleDot, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router'
import { ApiError } from '../api/client'
import type { CoverageRow, CoverageStatus } from '../api/models'
import { usePsCoverage } from '../api/queries'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { cx } from '../lib/cx'
import { Ledger } from '../overview/parts'

const ORDER: CoverageStatus[] = ['built', 'partly', 'planned']

/** A status in a word, an icon and a fill pattern: solid, hatched, empty. Never colour alone. */
const STATUS: Record<CoverageStatus, { words: string; Icon: LucideIcon; tag: string; cell: string; says: string }> = {
  built: {
    words: 'Built',
    Icon: CircleCheck,
    tag: 'border-ink bg-ink text-surface',
    cell: 'bg-ink border-ink',
    says: 'It works today, on a screen you can open, with a test or a command that fails if it stops.',
  },
  partly: {
    words: 'Partly built',
    Icon: CircleDot,
    tag: 'border-ink text-ink',
    cell: 'hatch border-ink-soft',
    says: 'Part of it works. The row says which part, and what is missing.',
  },
  planned: {
    words: 'Planned',
    Icon: CircleDashed,
    tag: 'border-dashed border-ink-dim text-ink-soft',
    cell: 'border-dashed border-ink-dim',
    says: 'Not built. The row says so.',
  },
}

function StatusTag({ status }: { status: CoverageStatus }) {
  const { words, Icon, tag } = STATUS[status]
  return (
    <span data-testid="coverage-status" data-status={status} className={cx('inline-flex h-6 w-fit shrink-0 items-center gap-1.5 whitespace-nowrap rounded-sm border px-1.5 text-sm font-semibold', tag)}>
      <Icon size={13} aria-hidden className="shrink-0" />
      {words}
    </span>
  )
}

/** The whole statement at a glance: one cell per line, in the statement's own order. */
function Strip({ rows }: { rows: CoverageRow[] }) {
  return (
    <ol aria-label="Every line, in the order of the problem statement" className="flex flex-wrap gap-1">
      {rows.map((r, i) => (
        <li key={r.id}>
          <a
            href={`#${r.id}`}
            title={`${i + 1}. ${STATUS[r.status].words}: ${r.text}`}
            aria-label={`Line ${i + 1}, ${STATUS[r.status].words}: ${r.text}`}
            className={cx('block h-6 w-6 border hover:outline hover:outline-1 hover:outline-offset-1 hover:outline-ink', STATUS[r.status].cell)}
          />
        </li>
      ))}
    </ol>
  )
}

function Row({ row, n }: { row: CoverageRow; n: number }) {
  return (
    <li id={row.id} className="grid scroll-mt-16 gap-x-6 gap-y-2 border-t border-rule-soft px-4 py-4 first:border-t-0 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <div className="flex flex-col gap-2">
        <span className="flex items-center gap-2">
          <span className="tabular w-6 font-mono text-sm text-ink-soft">{n}</span>
          <StatusTag status={row.status} />
        </span>
        <blockquote className="border-l-2 border-ink-dim pl-3 text-md text-ink">{row.text}</blockquote>
      </div>
      <div className="flex min-w-0 flex-col gap-2 text-base">
        <p className="text-ink">{row.what}</p>
        {row.gap && (
          <p className="text-ink">
            <span className="colhead mr-2">Not yet</span>
            {row.gap}
          </p>
        )}
        <p className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm text-ink-soft">
          <span>
            See it:{' '}
            <Link to={row.where} className="font-mono text-ink underline decoration-ink-dim underline-offset-2 hover:decoration-ink">
              {row.where}
            </Link>
          </span>
          <span className="min-w-0 break-all">
            {row.evidence_kind === 'make' ? 'Checked by the command ' : 'Checked by the test '}
            <span className="font-mono text-ink">{row.evidence_kind === 'make' ? `make ${row.evidence}` : row.evidence}</span>
          </span>
          {row.computed && <span>Worked out from the chains that trace today, not typed.</span>}
        </p>
      </div>
    </li>
  )
}

/** Every line of the problem statement, word for word, with what the tool does about it. */
export function CoveragePage() {
  const q = usePsCoverage()
  const d = q.data
  const sections = d ? [...new Set(d.rows.map((r) => r.section))] : []
  const numberOf = new Map(d?.rows.map((r, i) => [r.id, i + 1]))

  return (
    <>
      <PageHeader eyebrow="PS 26182 · Ministry of Home Affairs · I4C" title="Problem statement coverage">
        Every line of the problem statement, word for word, and what this tool does about it. A line is marked built only when there is a screen to see it on and a
        test or a command that fails if it stops being true. What is missing is said, not left out.
      </PageHeader>

      {q.isPending ? (
        <div aria-busy="true" className="flex flex-col gap-3">
          <Skeleton width="40%" />
          <Skeleton lines={6} />
        </div>
      ) : q.isError || !d ? (
        <ErrorState title="The coverage could not be read" detail={q.error instanceof ApiError ? q.error.detail : 'Reload the page to try again.'} onRetry={() => void q.refetch()} />
      ) : (
        <div className="flex flex-col gap-5">
          <Ledger
            label="Lines by status"
            entries={[
              ...ORDER.map((s) => ({ key: s, name: STATUS[s].words, value: String(d.counts[s] ?? 0), note: STATUS[s].says })),
              { key: 'all', name: 'Lines in the statement', value: String(d.total), note: d.source },
            ]}
          />
          <Strip rows={d.rows} />

          {sections.map((section) => (
            <section key={section} aria-label={section} className="flex flex-col gap-2">
              <h2 className="eyebrow">{section}</h2>
              <ol className="panel">
                {d.rows
                  .filter((r) => r.section === section)
                  .map((r) => (
                    <Row key={r.id} row={r} n={numberOf.get(r.id) ?? 0} />
                  ))}
              </ol>
            </section>
          ))}
        </div>
      )}
    </>
  )
}
