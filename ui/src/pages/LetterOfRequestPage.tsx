import { FileDown, Printer } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { ApiError } from '../api/client'
import { useLetterOfRequest, useMe } from '../api/queries'
import { Button, buttonClass } from '../components/Button'
import { ErrorState } from '../components/ErrorState'
import { PageHeader } from '../components/PageHeader'
import { Skeleton } from '../components/Skeleton'
import { DirectoryFacts } from '../desk/DirectoryFacts'
import { LetterSheet } from '../desk/LetterSheet'

const OFFICER_KEY = 'vaspfusion.officer'
const remembered = () => {
  try {
    return localStorage.getItem(OFFICER_KEY) ?? ''
  } catch {
    return ''
  }
}

/** The offshore route: a draft letter of request for a Court to issue to an authority outside India,
 *  for an exchange no source shows as registered with FIU-IND. Drawn from the same evidence as the
 *  domestic letter. It is made when the page is opened; the tool stores nothing and sends nothing,
 *  and the draft mark never comes off. */
export function LetterOfRequestPage() {
  const { name = '' } = useParams()
  const [params] = useSearchParams()
  const cases = params.getAll('case')
  const me = useMe()
  const officerId = useId()
  const signedIn = me.data?.officer ? [me.data.officer.name, me.data.officer.post].filter(Boolean).join(', ') : ''
  const [typed, setTyped] = useState<string | null>(null)
  const [asked, setAsked] = useState<string | null>(null)
  const officer = asked ?? (signedIn || remembered())
  const draft = useLetterOfRequest(name, officer, cases)
  const d = draft.data

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const line = (typed ?? officer).trim()
    if (!line) return
    try {
      localStorage.setItem(OFFICER_KEY, line)
    } catch {
      /* the name is still used for this draft */
    }
    setAsked(line)
  }

  const header = (
    <div className="print:hidden">
      <PageHeader
        eyebrow={
          <>
            <Link to="/desk">Request desk</Link> · <Link to={`/vasps/${encodeURIComponent(name)}`}>{name}</Link>
          </>
        }
        title={`Letter-of-request draft for ${d?.vasp ?? name}`}
      >
        For evidence held outside India. A Criminal Court issues a letter of request on the investigating officer's application; this is a draft for
        the officer and the Court. The tool keeps no copy and sends nothing.
      </PageHeader>
    </div>
  )

  const officerForm = (
    <form onSubmit={submit} className="flex flex-col gap-1.5 print:hidden">
      <label htmlFor={officerId} className="eyebrow">
        Investigating officer
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          id={officerId}
          value={typed ?? officer}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Name and post, as printed under the draft"
          className="min-w-0 flex-1 rounded border border-rule-strong bg-surface px-2.5 py-1.5 text-base text-fg"
        />
        <Button type="submit" variant={officer ? 'secondary' : 'primary'} disabled={!(typed ?? officer).trim()}>
          {officer ? 'Update draft' : 'Make draft'}
        </Button>
      </div>
    </form>
  )

  if (!officer.trim())
    return (
      <>
        {header}
        <div className="max-w-xl">
          {officerForm}
          <p className="mt-2 text-sm text-muted">The draft names the officer who would apply to the Court. Nothing is made until a name is given.</p>
        </div>
      </>
    )

  if (draft.isError)
    return (
      <>
        {header}
        <ErrorState
          title="No letter-of-request draft for this exchange"
          detail={draft.error instanceof ApiError ? draft.error.detail : 'Try again.'}
          onRetry={() => void draft.refetch()}
        />
        <div className="mt-4 max-w-xl">{officerForm}</div>
      </>
    )

  if (!d)
    return (
      <>
        {header}
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton width="40%" />
          <Skeleton width="60%" />
        </div>
      </>
    )

  const notes = d.letter.review_notes ?? []
  return (
    <>
      {header}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px] print:block">
        <aside aria-label="This draft: what it is, checks and the exchange" className="flex flex-col gap-6 lg:sticky lg:top-[76px] lg:order-2 print:hidden">
          <section aria-label="Standing" className="flex flex-col gap-2">
            <h2 className="eyebrow">Standing</h2>
            <p className="border-l-2 border-danger bg-danger-wash px-3 py-2 text-base text-fg">
              Draft. Not sent, and not a request of this desk: it has no reference and no status.
              {d.recommended ? ' For this exchange it takes the place of the domestic notice.' : ' It is offered beside the domestic notice; the officer decides which applies.'}
            </p>
            {officerForm}
          </section>

          <section aria-label="Check before use" className="flex flex-col gap-2">
            <h2 className="eyebrow">Check before use</h2>
            <ul className="flex flex-col gap-2 rounded border border-dashed border-rule-strong bg-surface px-3 py-2.5">
              {notes.map((note, i) => (
                <li key={i} className="flex gap-2 text-sm text-fg">
                  <span aria-hidden className="select-none text-muted">
                    –
                  </span>
                  <span className="min-w-0 [overflow-wrap:anywhere]">{note}</span>
                </li>
              ))}
            </ul>
          </section>

          <section aria-label={`On record for ${d.vasp}`} className="flex flex-col gap-2">
            <h2 className="eyebrow">On record for {d.vasp}</h2>
            <DirectoryFacts directory={d.directory} />
          </section>

          <section aria-label="On paper" className="flex flex-col gap-2">
            <h2 className="eyebrow">On paper</h2>
            <div className="flex flex-wrap gap-2">
              <Button icon={<Printer size={15} aria-hidden />} onClick={() => window.print()}>
                Print
              </Button>
              <a href={d.pdf_url} target="_blank" rel="noreferrer" className={buttonClass('secondary')}>
                <FileDown size={15} aria-hidden />
                Open draft PDF
              </a>
            </div>
            <p className="text-sm text-muted">Every page carries the draft mark and "Not sent".</p>
          </section>
        </aside>

        <div className="min-w-0 lg:order-1">
          <LetterSheet letter={d.letter} />
        </div>
      </div>
    </>
  )
}
