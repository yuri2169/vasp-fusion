/** Provenance — evidentiary defensibility.
 *
 * Nobody will ask for this. Building it anyway is the differentiator: an
 * intelligence product that cannot be reproduced or audited is worthless to the
 * consumer of it. Input hash, seed, feature version, git SHA, per-stage timings.
 */
import { useEffect, useState } from 'react';
import { api, fmt } from '../api';
import { Eyebrow, Notice, Panel, Spinner } from '../ui';

export function Provenance() {
  const [p, setP] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.provenance().then(setP).catch((e) => setErr(String(e))); }, []);

  if (err) return <div className="p-4"><Notice title="Could not load provenance" layer="danger">{err}</Notice></div>;
  if (!p) return <div className="p-8"><Spinner label="loading provenance…" /></div>;
  if (!p.provenance) return <div className="p-4"><Notice title="No run recorded yet" /></div>;

  const prov = p.provenance, r = p.receipt || {}, t = p.timings || {};
  const totalT = Object.values(t).reduce((a: number, b: any) => a + Number(b), 0);

  return (
    <div className="p-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3">
        <h1 className="display text-ink">provenance</h1>
        <span className="text-sm text-ink-soft">
          every figure traces to this input hash, this seed and this commit
        </span>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
      <Panel>
        <Eyebrow layer="data">run manifest</Eyebrow>
        <table className="w-full">
          <tbody>
            {[
              ['run id', p.run_id], ['created', fmt.time(String(p.created_at))],
              ['source file', prov.source_file],
              ['source bytes', fmt.int(prov.source_bytes)],
              ['seed', prov.seed], ['feature version', prov.feature_version],
              ['git sha', prov.git_sha], ['embedding backend', prov.embedding_backend],
            ].map(([k, v]) => (
              <tr key={String(k)} className="border-b border-rule-soft last:border-0">
                <td className="eyebrow py-2 w-44">{k}</td>
                <td className="mono text-sm py-2 break-all">{String(v ?? '—')}</td>
              </tr>
            ))}
            <tr>
              <td className="eyebrow py-2 align-top">source sha-256</td>
              <td className="mono text-2xs py-2 break-all leading-relaxed">
                {prov.source_sha256}
              </td>
            </tr>
          </tbody>
        </table>
      </Panel>

      <div className="space-y-3">
        <Panel>
          <Eyebrow layer="confirm" right={`${totalT.toFixed(2)}s total`}>per-stage timings</Eyebrow>
          <table className="w-full">
            <tbody>
              {Object.entries(t).map(([k, v]: [string, any]) => (
                <tr key={k} className="border-b border-rule-soft last:border-0">
                  <td className="text-sm py-1 w-28">{k}</td>
                  <td className="py-1">
                    <span className="inline-block h-2.5 bg-confirm"
                          style={{ width: `${(Number(v) / Math.max(totalT, 0.01)) * 100}%`, minWidth: 2 }} />
                  </td>
                  <td className="num mono text-2xs py-1 w-16">{Number(v).toFixed(2)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel>
          <Eyebrow layer="chain">ingest integrity</Eyebrow>
          <table className="w-full">
            <tbody>
              {[
                ['rows read', fmt.int(r.rows_read)],
                ['rows accepted', fmt.int(r.rows_clean)],
                ['rows quarantined', fmt.int(r.rows_quarantined)],
                ['duplicate announcements removed', fmt.int(r.duplicates_removed)],
                ['unmapped input columns', (r.unmapped_input_columns || []).join(', ') || 'none'],
                ['geoip source', String(r.enrichment?.geoip_source ?? '—')],
                ['supplied vs derived country mismatch',
                  fmt.int(Number(r.enrichment?.supplied_vs_derived_country_mismatch ?? 0))],
                ['supplied vs derived ASN mismatch',
                  fmt.int(Number(r.enrichment?.supplied_vs_derived_asn_mismatch ?? 0))],
              ].map(([k, v]) => (
                <tr key={String(k)} className="border-b border-rule-soft last:border-0">
                  <td className="text-sm py-2 text-ink-soft">{k}</td>
                  <td className="num mono text-sm py-2">{String(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-sm text-ink-soft mt-3">
            Rejected rows are quarantined with a reason, never dropped. Country and ASN are
            re-derived from the bundled GeoIP data and checked against the file.
          </p>
        </Panel>
      </div>
    </div>
    </div>
  );
}
