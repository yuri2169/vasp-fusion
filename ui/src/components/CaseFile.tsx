/** Plate 05 — the output artefact.
 *
 * Not an alert: an investigative document that has to survive being forwarded to
 * someone who has never seen this tool. Assessment in English, calibrated
 * confidence, evidence with real TXIDs, the graph path, the timeline, and the
 * network attribution.
 *
 * THE COUNTERFACTUAL BLOCK is the single most important element on this screen.
 * Every dashboard shows a number; none of them show what would move it. Analysts
 * reason about what evidence would confirm or collapse a hypothesis, so the
 * system states that explicitly — and because those lines are computed by
 * re-running the confidence model with one input changed, they are a property of
 * the model rather than copywriting.
 */
import { useEffect, useState } from 'react';
import { api, CASE_TIP, fmt, printUrl, watchlistPhrase, type CaseFile as CF, type WatchlistHit } from '../api';
import {
  Bar, Eyebrow, IconBack, IconCheck, IconExport, IconX, Notice, Panel, Spinner, Tag,
} from '../ui';
import { GraphView } from './GraphView';
import { featureLabel, featureValue } from '../featureLabels';
import { HourHistogram, TxTimeline } from './Charts';
import { ReasonChooser } from './ReasonChooser';

export function CaseFile({ entity, onBack }: { entity: string; onBack: () => void }) {
  const [d, setD] = useState<CF | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<'confirmed' | 'dismissed' | null>(null);
  const [near, setNear] = useState<WatchlistHit | null>(null);

  useEffect(() => {
    let live = true;
    setD(null); setErr(null);
    api.caseFile(entity)
      .then((r) => { if (live) { setD(r); setVerdict(r.alert.verdict || ''); } })
      .catch((e) => live && setErr(String(e)));
    setNear(null);
    api.watchlistHits()
      .then((h) => live && setNear(h.hits.find((x) => x.entity === entity) ?? null))
      .catch(() => {});
    return () => { live = false; };
  }, [entity]);

  async function decide(v: string, reason: string) {
    setBusy(true);
    try {
      await api.verdict(entity, v, reason);
      setVerdict(v);
    } finally { setBusy(false); }
  }

  if (err) return <div className="p-4"><Notice title="Could not load case file" layer="danger">{err}</Notice></div>;
  if (!d) return <div className="p-8"><Spinner label={`assembling case file for ${entity}…`} /></div>;

  const a = d.alert;
  // Each counterfactual belongs to one candidate address, and the line must say
  // which: "falls to 0.12 if it resolves to a shared VPN" is meaningless without
  // the address it is about. Dedupe on (text, address), not on text alone.
  const counterfactuals = [...new Map(
    d.attribution.flatMap((c) => (c.counterfactuals || []).map((cf) => ({ ...cf, ip: c.ip })))
      .map((c) => [`${c.text}|${c.ip}`, c]),
  ).values()].slice(0, 4);
  const top = d.attribution[0];

  return (
    <div className="p-3">
      {/* --- case header ---------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-rule px-1 py-2 sm:h-11 mb-3">
        <button onClick={onBack}
                className="text-sm flex items-center gap-2 text-ink-soft hover:text-ink cursor-pointer transition-colors duration-150">
          <IconBack /> alerts
        </button>
        <span className="w-px h-5 bg-rule" />
        <span className="font-cond font-extrabold uppercase text-lg tracking-tighter">
          Case file — {a.entity}
        </span>
        {a.case_id && (
          <span className="mono text-sm font-semibold text-fusion" title={CASE_TIP}>{a.case_id}</span>
        )}
        <span className="text-2xs text-ink-dim hidden sm:inline">rank <span className="mono">{a.rank}</span> · run <span className="mono">{d.run_id}</span></span>
        <div className="ml-auto flex flex-wrap items-center gap-2 no-print">
          {verdict
            ? <Tag layer={verdict === 'confirmed' ? 'confirm' : 'data'}>{verdict}</Tag>
            : null}
          <a href={api.exportUrl(entity)} target="_blank" rel="noreferrer"
             className="text-sm px-3 h-7 inline-flex items-center gap-2 border border-rule
                        text-ink-soft hover:text-ink hover:border-ink transition-colors duration-150">
            <IconExport /> export
          </a>
          <button onClick={() => printUrl(`${api.exportUrl(entity)}?inline=1`)}
                  title="Opens the print dialog - choose Save as PDF"
                  className="text-sm px-3 h-7 inline-flex items-center gap-2 border border-rule
                             text-ink-soft hover:text-ink hover:border-ink transition-colors
                             duration-150 cursor-pointer">
            <IconExport /> PDF
          </button>
          {pending && (
            <ReasonChooser entity={entity} verdict={pending}
                           onCancel={() => setPending(null)}
                           onSave={(r) => { decide(pending, r); setPending(null); }} />
          )}
          <button onClick={() => setPending('confirmed')} disabled={busy}
                  className="text-sm px-3 h-7 inline-flex items-center gap-2
                             transition-opacity duration-150 hover:opacity-85 cursor-pointer
                             disabled:opacity-40 disabled:cursor-default"
                  style={{ background: 'var(--confirm)', color: 'var(--surface)' }}>
            <IconCheck /> confirm
          </button>
          <button onClick={() => setPending('dismissed')} disabled={busy}
                  className="text-sm px-3 h-7 inline-flex items-center gap-2 border
                             border-rule text-ink-soft hover:text-ink hover:border-ink
                             transition-colors duration-150
                             disabled:opacity-40 disabled:cursor-default">
            <IconX /> dismiss
          </button>
        </div>
      </div>

      {/* Asymmetric split, as the wireframe specifies: evidence reads as a
          column; the graph needs width. Equal halves would serve neither. */}
      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] gap-3">
        {/* ================= LEFT: the argument ============================ */}
        <div className="space-y-3 min-w-0">
          <Panel accent="fusion">
            <Eyebrow layer="fusion">assessment</Eyebrow>
            <p className="text-md leading-relaxed">{a.narrative}</p>
          </Panel>

          {/* Analyst-supplied intelligence, kept visibly apart from the model's
              assessment above: it is a reason to look, not part of the score. */}
          {near && (
            <Notice title="Watchlist" layer="danger">
              {watchlistPhrase(near)}
              {near.path.length > 1 && (
                <> via <span className="mono text-2xs">{near.path.join(' → ')}</span></>
              )}. Not part of the model's score.
            </Notice>
          )}

          {/* One case is one operation: the linked actors that paid each other
              ride along with the lead rather than taking 29 queue rows. */}
          {d.case && d.case.members.length > 1 && (
            <Panel>
              <details>
                <summary className="cursor-pointer flex items-baseline gap-3" title={CASE_TIP}>
                  <span className="eyebrow" style={{ color: 'var(--fusion)' }}>
                    members ({fmt.int(d.case.n_linked + 1)})
                  </span>
                  <span className="text-sm text-ink-soft">
                    this operation · money moved between members
                  </span>
                </summary>
                <table className="w-full mt-2">
                  <thead>
                    <tr className="border-b border-rule">
                      {['actor', 'payments sent', 'BTC in', 'BTC out'].map((h, i) => (
                        <th key={h} className={`colhead py-1.5 ${i ? 'text-right' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {d.case.members.map((m) => (
                      <tr key={m.entity} className="border-b border-rule-soft last:border-0">
                        <td className={`mono text-sm py-1.5 ${m.entity === a.entity ? 'font-semibold' : ''}`}>
                          {m.entity}{m.entity === a.entity ? ' (lead)' : ''}
                        </td>
                        <td className="num mono text-sm py-1.5">{fmt.int(m.n_tx)}</td>
                        <td className="num mono text-sm py-1.5 text-chain">{fmt.btc(m.value_in)}</td>
                        <td className="num mono text-sm py-1.5 text-chain">{fmt.btc(m.value_out)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {d.case.n_linked + 1 > d.case.members.length && (
                  <p className="text-2xs text-ink-dim mt-2">
                    showing the first {d.case.members.length} of {fmt.int(d.case.n_linked + 1)} members
                  </p>
                )}
                {!d.case.full_graph && (
                  <p className="text-2xs text-ink-dim mt-2">
                    This run predates full-graph storage; payments between members may be undercounted.
                  </p>
                )}
              </details>
            </Panel>
          )}

          <Panel>
            <Eyebrow layer="fusion"
                     right={a.confidence_unadjusted != null ? 'calibrated · at this capture\'s base rate' : 'isotonic-calibrated'}>
              confidence
            </Eyebrow>
            {/* Two different uncertainties, each named. The ± is how much evidence
                this actor has (its own transaction count); the range is how much
                calibration data sits near this score (Venn-Abers). Unlabelled, a
                wide ± next to a tight range reads as a contradiction. */}
            <div className="flex items-end gap-3">
              <span className="font-cond font-bold text-3xl leading-none">{fmt.conf(a.confidence)}</span>
              <span className="mono text-sm text-ink-soft pb-1">
                {fmt.range(a.confidence, a.interval)} <span className="text-2xs text-ink-dim">from this actor's volume</span>
              </span>
            </div>
            {a.confidence_low != null && a.confidence_high != null && (
              <div className="mono text-2xs text-ink-soft mt-1">
                calibration range{' '}
                <b className="text-ink">
                  {fmt.conf(a.confidence_low) === fmt.conf(a.confidence_high)
                    ? `${fmt.conf(a.confidence_low)}, under 0.01 wide`
                    : `${fmt.conf(a.confidence_low)}–${fmt.conf(a.confidence_high)}`}
                </b>
              </div>
            )}
            {a.confidence_unadjusted != null && fmt.conf(a.confidence_unadjusted) !== fmt.conf(a.confidence) && (
              <div className="mono text-2xs text-ink-dim mt-1">
                {fmt.conf(a.confidence_unadjusted)} at the training base rate — the alert gate uses that value
              </div>
            )}
            <div className="mt-3">
              <Bar value={a.confidence} layer="fusion" width="100%" height={10} />
            </div>
            <div className="flex gap-4 mt-2 mono text-2xs text-ink-dim">
              <span>supervised <b className="text-ink">{fmt.conf(a.supervised)}</b></span>
              <span>novelty <b className="text-ink">{fmt.conf(a.novelty)}</b></span>
              <span>evidence <b className="text-ink">{fmt.conf(a.evidence_strength)}</b></span>
            </div>

            {counterfactuals.length > 0 && (
              <div className="mt-3 bg-surface-2 p-3">
                <Eyebrow layer="network">what would change this</Eyebrow>
                <ul className="space-y-2">
                  {counterfactuals.map((c, i) => (
                    <li key={i} className="text-sm flex gap-2">
                      <span className="mono font-semibold shrink-0"
                            style={{ color: c.direction === 'down' ? 'var(--danger)' : 'var(--confirm)' }}>
                        {c.direction === 'down' ? '↓' : '↑'} {c.value.toFixed(2)}
                      </span>
                      <span className="text-ink-soft">
                        <span className="mono text-ink">{c.ip}</span>{' '}
                        {c.text.replace(/^(falls|rises) to [\d.]+ /, '')}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>

          {d.evidence.length > 0 && (
            <Panel>
              <Eyebrow layer="chain" right={`${d.evidence.length} matcher${d.evidence.length > 1 ? 's' : ''}`}>
                evidence chain
              </Eyebrow>
              <div className="space-y-3">
                {d.evidence.map((e, i) => (
                  <div key={i} className="border border-rule-soft bg-surface-2">
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-rule-soft">
                      <Tag layer="fusion">{fmt.typology(e.typology)}</Tag>
                      <span className="mono text-2xs text-ink-dim">strength {e.strength.toFixed(2)}</span>
                    </div>
                    <p className="px-3 py-2 text-sm text-ink-soft">{e.summary}</p>
                    {e.detail?.length > 0 && (
                      <table className="w-full border-t border-rule-soft">
                        <tbody>
                          {e.detail.map((row, j) => (
                            <tr key={j} className="border-b border-rule-soft last:border-0">
                              {Object.entries(row).map(([k, v]) => (
                                <td key={k} className="px-3 py-1 mono text-2xs">
                                  <span className="text-ink-dim">{k.replace(/_/g, ' ')} </span>
                                  <span className="text-ink">{String(v).length > 24
                                    ? `${String(v).slice(0, 22)}…` : String(v)}</span>
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                ))}
              </div>
            </Panel>
          )}

          {d.shap.length > 0 && (
            <Panel>
              <Eyebrow layer="fusion">model attributions (SHAP)</Eyebrow>
              <table className="w-full">
                <tbody>
                  {d.shap.slice(0, 8).map((s) => (
                    <tr key={s.feature} className="border-b border-rule-soft last:border-0">
                      <td className="text-sm py-2 pr-2 w-56" title={s.feature}>
                        {featureLabel(s.feature)}
                        <span className="mono text-2xs text-ink-dim"> · {featureValue(s.feature, s.value)}</span>
                      </td>
                      <td className="py-2 w-32">
                        <Bar value={Math.abs(s.contribution)}
                             max={Math.abs(d.shap[0].contribution) || 1}
                             negative={s.contribution < 0} width={110} height={9} />
                      </td>
                      <td className="mono text-2xs num py-2 pl-2 w-16"
                          style={{ color: s.contribution > 0 ? 'var(--fusion)' : 'var(--data)' }}>
                        {s.contribution > 0 ? '+' : ''}{s.contribution.toFixed(3)}
                      </td>
                      <td className="text-2xs text-ink-dim py-2 pl-3 hidden 2xl:table-cell">
                        {s.meaning}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
        </div>

        {/* ================= RIGHT: the picture ============================ */}
        <div className="space-y-3 min-w-0">
          <Panel pad={false}>
            <div className="px-4 pt-3">
              <Eyebrow layer="chain">link analysis</Eyebrow>
            </div>
            <GraphView entity={entity} />
          </Panel>

          {d.transactions.length > 0 && (
            <Panel>
              <Eyebrow layer="chain" right={`${d.transactions.length} transactions`}>
                activity timeline
              </Eyebrow>
              <TxTimeline txs={d.transactions} />
            </Panel>
          )}

          <Panel accent={top ? 'network' : undefined}>
            <Eyebrow layer="network" right={a.attribution_status?.replace(/_/g, ' ')}>network attribution</Eyebrow>
            {d.attribution.length === 0 ? (
              <p className="text-sm text-ink-soft">
                {a.attribution_status === 'suppressed'
                  ? 'Every candidate address is shared infrastructure — a Tor exit, a commercial VPN endpoint, or a host observed announcing for many unrelated entities. Attribution is suppressed rather than reported at a confidence that would mislead.'
                  : a.attribution_status === 'no_significant_link'
                    ? 'No entity-IP association survived FDR control. The observed co-occurrences are consistent with chance given each address’s traffic volume.'
                    : 'No network layer available in this capture; chain-side detection is unaffected.'}
              </p>
            ) : (
              <>
                <div className="overflow-x-auto scroll-hint">
                <table className="w-full min-w-[34rem]">
                  <thead>
                    <tr className="border-b border-rule">
                      {['address', 'asn', 'type', 'obs', 'roots', 'p', 'confidence'].map((h, i) => (
                        <th key={h} className={`colhead py-2 ${i >= 3 ? 'text-right' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {d.attribution.map((c) => (
                      <tr key={c.ip} className="border-b border-rule-soft last:border-0">
                        <td className="mono text-sm py-2">{c.ip}</td>
                        <td className="mono text-2xs py-2 max-w-[9rem] truncate" title={c.asn_org}>
                          AS{c.asn}
                        </td>
                        <td className="py-2"><Tag layer="network">{c.asn_type}</Tag></td>
                        <td className="mono text-2xs num py-2">{c.n_observations}</td>
                        <td className="mono text-2xs num py-2">{c.root_hits}</td>
                        <td className="mono text-2xs num py-2">{c.p_value.toExponential(1)}</td>
                        <td className="num py-2">
                          <span className="mono text-md font-semibold">{fmt.conf(c.confidence)}</span>
                          <span className="mono text-2xs text-ink-dim"> {fmt.range(c.confidence, c.interval)}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
                <p className="mono text-2xs text-network mt-2 leading-relaxed">
                  Diffusion-adjusted: propagation roots outrank first sightings; shared infrastructure is penalised.
                </p>
              </>
            )}
          </Panel>

          {d.behaviour && d.behaviour.diurnality > 0.05 && (
            <Panel>
              <Eyebrow layer="network"
                       right={`fit ${d.behaviour.offset_fit.toFixed(2)} · diurnality ${d.behaviour.diurnality.toFixed(2)}`}>
                behavioural timezone
              </Eyebrow>
              <HourHistogram hist={d.behaviour.hour_histogram}
                             offsetMin={d.behaviour.inferred_offset_min} />
              <p className="text-sm text-ink-soft mt-2">
                Activity is most consistent with an operator in{' '}
                <b className="mono">{fmt.offset(d.behaviour.inferred_offset_min)}</b>, from activity
                hours alone, independent of GeoIP.
              </p>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
