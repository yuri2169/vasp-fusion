import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router'
import type { DestinationsByJurisdiction, JurisdictionExchange } from '../api/models'
import { useRupees } from '../components/Rupees'
import { formatDate, formatUsd } from '../lib/format'
import { Panel } from './parts'
import { PLACES } from './places'
import { plural } from './words'

const WorldMap = lazy(() => import('./WorldMap'))

const link = 'underline decoration-rule-strong underline-offset-2 hover:decoration-current'

/** The registration as the directory cites it: always with its date, and "no source" is not "no". */
function fiu(e: JurisdictionExchange): string {
  if (e.fiu_ind_registered == null) return 'No source'
  const when = e.fiu_ind_as_of ? `, as of ${formatDate(e.fiu_ind_as_of)}` : ''
  return `${e.fiu_ind_registered ? 'Registered' : 'Not registered'}${when}`
}

/** Traced money by the country each exchange is registered in, on a map and as the table behind it.
 *  The country is the directory's cited jurisdiction; an exchange with none is listed apart. */
export function JurisdictionPanel({ data, scope, className }: { data: DestinationsByJurisdiction; scope: 'all' | 'case'; className?: string }) {
  const [selected, setSelected] = useState<string | null>(null)
  const rupees = useRupees()
  const money = (usd: number, unpriced: number) =>
    usd > 0 || unpriced === 0 ? [formatUsd(usd), rupees(usd)].filter(Boolean).join(' · ') : 'Not a dollar asset'
  const top = Math.max(...data.places.map((p) => p.total_usd), 0)
  const places = data.places.map((p) => ({
    name: p.jurisdiction,
    share: top > 0 ? p.total_usd / top : 0.35,
    label: `${p.jurisdiction}: ${money(p.total_usd, p.unpriced_wallets ?? 0)}, ${plural(p.case_ids.length, 'case')}, ${p.exchanges.map((e) => e.vasp).join(', ')}`,
  }))
  const shown = data.places.filter((p) => selected == null || p.jurisdiction === selected)
  const undrawn = data.places.filter((p) => !PLACES[p.jurisdiction]).map((p) => p.jurisdiction)
  const nothing = data.places.length === 0 && data.not_on_record.length === 0
  return (
    <Panel
      title="Where the traced money went"
      className={className}
      note={`${data.basis} The country is the one a cited source gives for each exchange; this tool holds no location data on any wallet.`}
    >
      {nothing ? (
        <p className="px-1.5 text-base text-muted">{scope === 'case' ? 'This case names no exchange at or above the bar, so there is nothing to place.' : 'No finished case names an exchange yet.'}</p>
      ) : (
        <>
          {data.places.length > 0 && (
            <div className="rounded border border-rule bg-surface p-1">
              <Suspense fallback={<div className="aspect-[2/1] w-full" aria-hidden="true" />}>
                <WorldMap places={places} selected={selected} onSelect={setSelected} />
              </Suspense>
            </div>
          )}
          {undrawn.length > 0 && <p className="px-1.5 text-sm text-muted">Listed below but not drawn (no point on file for it): {undrawn.join(', ')}.</p>}
          {data.places.length > 0 && (
            <div className="overflow-auto rounded border border-rule">
              <table className="w-full border-collapse text-base">
                <caption className="sr-only">Traced money by the jurisdiction of the exchange it reached</caption>
                <thead>
                  <tr className="bg-sunk">
                    {['Jurisdiction', 'Exchange', 'FIU-IND', 'Traced', 'Cases', 'Source'].map((h, i) => (
                      <th key={h} scope="col" className={`eyebrow px-3 py-2 ${i === 3 || i === 4 ? 'text-right' : 'text-left'}`}>
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {shown.flatMap((p) =>
                    p.exchanges.map((e, i) => (
                      <tr key={`${p.jurisdiction}/${e.vasp}`} className="border-t border-rule align-top">
                        {i === 0 && (
                          <th scope="rowgroup" rowSpan={p.exchanges.length} className="px-3 py-2 text-left font-medium text-fg">
                            {p.jurisdiction}
                          </th>
                        )}
                        <td className="px-3 py-2">
                          <Link to={`/vasps/${encodeURIComponent(e.vasp)}`} className={`text-fg ${link}`}>
                            {e.vasp}
                          </Link>
                        </td>
                        <td className={`px-3 py-2 ${e.fiu_ind_registered == null ? 'text-muted' : 'text-fg'}`}>{fiu(e)}</td>
                        <td className="tabular px-3 py-2 text-right font-mono text-fg">{money(e.total_usd, e.unpriced_wallets ?? 0)}</td>
                        <td className="tabular px-3 py-2 text-right font-mono text-fg">{e.case_ids.length}</td>
                        <td className="px-3 py-2">
                          {(e.source_urls ?? []).map((u, n) => (
                            <a key={u} href={u} target="_blank" rel="noopener noreferrer" className={`mr-2 text-fg ${link}`}>
                              {new URL(u).hostname.replace(/^www\./, '')}
                              {(e.source_urls ?? []).length > 1 ? ` (${n + 1})` : ''}
                            </a>
                          ))}
                        </td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          )}
          {data.places.length > 0 && (
            <p className="px-1.5 text-sm text-muted">
              Each country is what the linked source gives for the company that operates the exchange. A source can give an office and not a place of incorporation, or name
              one company of several: the exchange's own page says which, in the source's words.
            </p>
          )}
          {selected != null && (
            <p className="px-1.5 text-sm text-muted">
              Showing {selected} only.{' '}
              <button type="button" className={`text-fg ${link}`} onClick={() => setSelected(null)}>
                Show every jurisdiction
              </button>
            </p>
          )}
          {data.not_on_record.length > 0 && (
            <p className="px-1.5 text-base text-fg" aria-label="Jurisdiction not on record">
              <strong className="font-semibold">Jurisdiction not on record:</strong>{' '}
              {data.not_on_record.map((e) => `${e.vasp} (${money(e.total_usd, e.unpriced_wallets ?? 0)})`).join(', ')}.{' '}
              <span className="text-muted">No cited source gives a country for {data.not_on_record.length === 1 ? 'it' : 'these'}, so none is shown.</span>
            </p>
          )}
        </>
      )}
    </Panel>
  )
}
