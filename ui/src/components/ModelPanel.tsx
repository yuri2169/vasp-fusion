/** Plate 06 — model transparency.
 *
 * The screen that wins the Q&A round. Most teams hide the model; this one opens
 * it: calibration curve, ablation lift, held-out-typology performance, the
 * generator leak test, and the numbers we are NOT proud of, shown at the same
 * size as the ones we are.
 *
 * Nothing here is hardcoded. Every figure is read from artifacts/v1/metrics.json,
 * which `make train` regenerates from a fixed seed — so what the panel shows and
 * what the write-up claims cannot drift apart.
 */
import { useEffect, useState } from 'react';
import { api } from '../api';
import { Bar, Counter, Eyebrow, Notice, Panel, Spinner, Tag } from '../ui';
import { ReliabilityCurve, RiskCoverageCurve } from './Charts';
import { SensitivityCurve, chanceOf } from './SensitivityCurve';

const pct = (v: number | undefined | null) =>
  v === undefined || v === null || Number.isNaN(v) ? '—' : v.toFixed(3);
const int = (v: number | undefined | null) => (v ?? 0).toLocaleString();
const pc = (v: number) => `${(v * 100).toFixed(0)}%`;

/** "k / n correct · 95% range lo–hi" for a precision measured on n alerts (Wilson score interval). */
export function hits(p: number | undefined | null, n: number) {
  if (p === undefined || p === null || Number.isNaN(p)) return '';
  const z2 = 1.96 ** 2, k = Math.round(p * n), q = k / n;
  const mid = (q + z2 / (2 * n)) / (1 + z2 / n);
  const half = 1.96 * Math.sqrt(q * (1 - q) / n + z2 / (4 * n * n)) / (1 + z2 / n);
  return `${k} / ${n} correct · 95% range ${(mid - half).toFixed(2)}–${(mid + half).toFixed(2)}`;
}

/** A figure whose source file does not exist yet. Never a placeholder number. */
const Unmeasured = () => <span className="text-2xs text-ink-dim">not yet measured</span>;

const SHARED_EXITS = new Set(['vpn', 'tor', 'cdn']);

function Row({ label, value, layer, note }: {
  label: string; value: string; layer?: 'fusion' | 'confirm' | 'network' | 'danger' | 'chain'; note?: string;
}) {
  return (
    <tr className="border-b border-rule-soft last:border-0">
      <td className="py-2 text-sm text-ink-soft">{label}
        {note ? <span className="block mono text-2xs text-ink-dim">{note}</span> : null}
      </td>
      <td className="py-2 num mono text-md font-semibold"
          style={layer ? { color: `var(--${layer})` } : undefined}>{value}</td>
    </tr>
  );
}

export function ModelPanel() {
  const [m, setM] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.model().then(setM).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="p-4"><Notice title="Could not load model panel" layer="danger">{err}</Notice></div>;
  if (!m) return <div className="p-8"><Spinner label="loading model artefacts…" /></div>;
  if (!m.available) return (
    <div className="p-4">
      <Notice title="No trained artefacts">
        {m.note} Run <span className="mono">make train</span> to fit the models and produce{' '}
        <span className="mono">metrics.json</span>.
      </Notice>
    </div>
  );

  const man = m.manifest;
  const met = man.metrics || {};
  const res = met.results || {};
  const test = res.test || {};
  const ho = res.holdout_typology || {};
  const leak = m.leak_test;
  const abl: any[] = met.ablation || [];
  const maxAbl = Math.max(...abl.map((a) => a.pr_auc || 0), 0.01);
  const R = m.research || {};

  return (
    <div className="p-3 space-y-3">

    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3">

      <h1 className="display text-ink">model</h1>


    </div>
      {/* provenance strip */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 bg-surface-2 border-y border-rule px-4 py-2">
        <span className="font-cond font-bold text-md text-ink">Model panel</span>
        <span className="mono text-2xs text-ink-soft">
          artifacts/{man.version} · feature_version {man.feature_version} · seed {man.seed}
          {' '}· git {String(man.provenance?.git_sha ?? '—')}
        </span>
        <span className="mono text-2xs text-ink-soft">
          backend <b className="text-ink">{man.backend}</b> · {man.n_features} features
          · {Number(man.n_train_rows).toLocaleString()} training entities
        </span>
        {/* A filled amber pill. It used to inherit white from the dark strip;
            with the strip tokenised it inherited ink and fell to 2.98:1.
            --surface inverts with the theme, so it reads on the dark amber of
            light mode and the light amber of dark mode alike. */}
        <span className="ml-auto mono text-2xs px-2 py-0.5"
              style={{ background: 'var(--fusion)', color: 'var(--surface)' }}>
          make reproduce
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Panel>
          <Eyebrow layer="fusion">calibration — reliability diagram</Eyebrow>
          {test.calibration_study ? (
            <ReliabilityCurve points={test.calibration_study.after_prior_shift.reliability}
                              ece={test.calibration_study.after_prior_shift.ece} />
          ) : (
            <ReliabilityCurve points={met.reliability_curve || []} ece={test.ece ?? 0} />
          )}
          <p className="text-sm text-ink-soft mt-2">
            Isotonic regression, fitted on a fold the test set never touches
            {test.calibration_study ? ', then moved to the test fold\'s own base rate — the probability the queue shows' : ''}.
          </p>
        </Panel>

        <Panel weight="primary">
          <Eyebrow layer="fusion">ablation — where the lift comes from</Eyebrow>
          <table className="w-full">
            <tbody>
              {/* Staggered so the sequence reads as an argument rather than a
                  table: rules barely move, then the model arrives. This is the
                  strongest claim in the submission and it was static. */}
              {abl.map((a, i) => (
                <tr key={a.stage} className="border-b border-rule-soft last:border-0 anim-rise"
                    style={{ animationDelay: `${i * 110}ms` }}>
                  <td className="py-2 text-sm pr-2">{a.stage}</td>
                  <td className="py-2 w-28">
                    <Bar value={a.pr_auc} max={maxAbl}
                         layer={a.stage.includes('rules') || a.stage.includes('unsupervised')
                           ? 'data' : 'fusion'} width={100} height={11}
                         delay={i * 110 + 90} />
                  </td>
                  <td className="py-2 num mono text-sm font-semibold w-14">
                    <Counter value={a.pr_auc} decimals={3} duration={620} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mono text-2xs text-network mt-2 leading-relaxed">
            Rules alone sit near the base rate. The lift is the model.
          </p>
        </Panel>

        <Panel>
          <Eyebrow layer="fusion" right="held-out test fold">scorecard</Eyebrow>
          <table className="w-full">
            <tbody>
              <Row label="PR-AUC" value={pct(test.pr_auc)} layer="fusion"
                   note={`base rate ${pct(test.baseline_pr_auc)} — the number to beat`} />
              {test.queue?.raw_score_then_value && (
                <Row label="Precision @ 10 · queue order" layer="confirm"
                     value={pct(test.queue.raw_score_then_value.precision_at_10)}
                     note={`ranked the way the alert queue ships · ${hits(test.queue.raw_score_then_value.precision_at_10, 10)}`} />
              )}
              <Row label="Precision @ 10 · by probability" value={pct(test.precision_at_10)}
                   note={`ranked by calibrated probability · ${hits(test.precision_at_10, 10)}`} />
              <Row label="Precision @ 50" value={pct(test.precision_at_50)}
                   note={hits(test.precision_at_50, 50)} />
              {test.classification && (
                <Row label="Precision · every alert flagged" value={pct(test.classification.precision)}
                     note={`${int(test.classification.tp)} of ${int(test.classification.tp + test.classification.fp)} alerts above the ${test.classification.threshold} threshold were laundering — where 1.000 stops`} />
              )}
              <Row label="Recall @ precision 0.80" value={pct(test.recall_at_precision_80)} />
              {test.calibration_study ? (
                <Row label="Expected calibration error"
                     value={pct(test.calibration_study.after_prior_shift.ece)}
                     layer={test.calibration_study.after_prior_shift.ece < 0.05 ? 'confirm' : 'fusion'}
                     note={`as the queue shows it · ${pct(test.calibration_study.before.ece)} before the base-rate correction · target < 0.05`} />
              ) : (
                <Row label="Expected calibration error" value={pct(test.ece)}
                     layer={(test.ece ?? 1) < 0.05 ? 'confirm' : 'fusion'} note="target < 0.05" />
              )}
              <Row label="Held-out typology recall" value={pct(ho.recall_at_threshold)}
                   layer="network"
                   note="laundering patterns never trained on" />
              {test.classification && (<>
                <Row label="F1 (operating threshold)" value={pct(test.classification.f1)}
                     layer="fusion" />
                <Row label="MCC" value={pct(test.classification.mcc)} layer="fusion"
                     note="robust to class imbalance" />
                <Row label="Accuracy" value={pct(test.classification.accuracy)}
                     note={`all-licit baseline ${pct(test.classification.accuracy_all_negative_baseline)}`} />
              </>)}
            </tbody>
          </table>
          <p className="mono text-2xs text-ink-dim mt-2 leading-relaxed">
            Precision @ k counts only the k alerts the model is surest of, so a perfect score
            there is expected. The whole fold — {int(test.n_positive)} laundering entities among {int(test.n)} —
            is judged by PR-AUC, recall and the flagged-alert precision.
          </p>
        </Panel>
      </div>

      {/* The honest numbers, given the same weight as the flattering ones. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel accent={leak?.passed ? 'confirm' : 'danger'}>
          <Eyebrow layer={leak?.passed ? 'confirm' : 'danger'}>generator integrity — leak test</Eyebrow>
          {!leak ? <p className="text-sm text-ink-soft">Not run. <span className="mono">make leak-test</span></p> : (
            <>
              <div className="flex items-center gap-3 mb-2">
                <span className="font-cond font-bold uppercase text-lg"
                      style={{ color: leak.passed ? 'var(--confirm)' : 'var(--danger)' }}>
                  {leak.passed ? 'PASSED' : 'FAILED'}
                </span>
                <span className="flex flex-wrap items-center gap-2">
                  <Tag layer={leak.passed ? 'confirm' : 'danger'}>
                    strict tier {leak.lift_over_baseline}× baseline
                  </Tag>
                  <Tag layer="fusion">full model {leak.control_lift}×</Tag>
                </span>
              </div>
              <p className="text-sm text-ink-soft">
                Fields with no constructed path to the label score near the base rate, so detection
                comes from topology, timing and network structure, not from how the data was written.
              </p>
              <table className="w-full mt-2">
                <tbody>
                  {Object.entries(leak.per_field || {}).map(([f, v]: [string, any]) => (
                    <tr key={f} className="border-b border-rule-soft last:border-0">
                      <td className="mono text-2xs py-1">{f}</td>
                      <td className="py-1"><Tag layer={v.tier === 'strict' ? 'chain' : 'data'}>{v.tier}</Tag></td>
                      <td className="num mono text-2xs py-1"
                          style={{ color: v.tier === 'strict' && v.lift > 1.3 ? 'var(--danger)' : undefined }}>
                        {v.lift}×
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </Panel>

        <div className="space-y-3">
          <Panel>
            <Eyebrow layer="network">generalisation to unseen typologies</Eyebrow>
            <div className="flex items-end gap-3 mb-2">
              <span className="font-cond font-bold text-3xl leading-none">{pct(ho.recall_at_threshold)}</span>
              <span className="mono text-sm text-ink-soft pb-1">
                recall on {ho.n_holdout_positives ?? 0} entities · PR-AUC {pct(ho.pr_auc)}
              </span>
            </div>
            <p className="text-sm text-ink-soft">
              <b className="mono">{(ho.typologies || []).join(', ')}</b> were held out of training
              entirely. The gap to the test score bounds how it handles a pattern nobody anticipated.
            </p>
          </Panel>

          <Panel>
            <Eyebrow layer="chain">entity resolution quality</Eyebrow>
            <table className="w-full">
              <tbody>
                <Row label="Addresses clustered"
                     value={Number(met.entity_resolution?.n_addresses ?? 0).toLocaleString()} />
                <Row label="Entities recovered"
                     value={Number(met.entity_resolution?.n_entities ?? 0).toLocaleString()} />
                <Row label="Co-spend edges (heuristic H1)"
                     value={Number(met.entity_resolution?.cospend_edges ?? 0).toLocaleString()}
                     note="common-input-ownership" />
                <Row label="Change edges (heuristic H2)"
                     value={Number(met.entity_resolution?.change_edges ?? 0).toLocaleString()}
                     note="script-type-refined change detection" />
                <Row label="Mean cluster purity"
                     value={pct(met.label_mapping?.mean_purity)} layer="confirm"
                     note="clusters almost never merge two real actors" />
              </tbody>
            </table>
          </Panel>
        </div>
      </div>


      {/* The differentiator, measured - and the curve it sits on. */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {met.attribution && (() => {
          const at = met.attribution;
          const o = at.outcomes;
          const pol = at.policy;
          const fixed = at.at_fixed_threshold;
          return (
          <Panel>
            <Eyebrow layer="network" right={`${int(at.n_evaluable)} gradable entities`}>
              attribution accuracy — the differentiator, measured
            </Eyebrow>
            <div className="flex flex-wrap items-end gap-x-6 gap-y-2 mb-2">
              <div>
                <div className="font-cond font-bold text-3xl leading-none">{pct(at.top1_accuracy)}</div>
                <div className="mono text-2xs text-ink-dim">top-1 · of those answered</div>
              </div>
              {at.top1_over_evaluable != null && (
                <div>
                  <div className="font-cond font-bold text-3xl leading-none">{pct(at.top1_over_evaluable)}</div>
                  <div className="mono text-2xs text-ink-dim">top-1 · every abstention a miss</div>
                </div>
              )}
              <div className="mono text-sm text-ink-soft pb-1">
                vs <b>{pct(at.random_choice_expected ?? at.random_choice_baseline)}</b> for random
                choice among {Number(at.mean_candidates).toFixed(1)} candidates
              </div>
            </div>
            {o && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-rule-soft mb-3">
                {[
                  ['correct', o.correct, 'confirm', 'answered, right'],
                  ['wrong', o.wrong, 'danger', 'answered, wrong'],
                  ['declined', o.correct_abstain, 'confirm', "origin's IP never observed"],
                  ['withheld', o.unnecessary_abstain, 'fusion', 'origin observed, still declined'],
                ].map(([k, v, layer, sub]) => (
                  <div key={k as string} className="bg-surface px-2 py-1.5">
                    <div className="num mono text-md font-semibold" style={{ color: `var(--${layer})` }}>
                      {int(v as number)}
                    </div>
                    <div className="text-2xs text-ink-soft">{k as string}</div>
                    <div className="mono text-2xs text-ink-dim">{sub as string}</div>
                  </div>
                ))}
              </div>
            )}
            <table className="w-full">
              <tbody>
                <Row label="Top-3 accuracy" value={pct(at.top3_accuracy)} />
                <Row label="Mean reciprocal rank" value={pct(at.mrr)} />
                <Row label="Attempt rate" value={pct(at.attempt_rate)}
                     note="how often the engine was willing to answer at all" />
                {!o && (
                  <Row label="Abstentions" value={String(at.n_abstained)} layer="confirm"
                       note="shared infrastructure — correctly declined rather than guessed" />
                )}
                <Row label="Single-candidate share" value={pct(at.single_candidate_share)}
                     note="cases where top-1 was trivially correct" />
              </tbody>
            </table>
            {pol?.threshold_map && (
              <>
                <div className="eyebrow mt-3 mb-1">
                  when it answers — fitted per host class, error ≤ {pol.target_risk} at{' '}
                  {pc(1 - pol.delta)} confidence
                </div>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-rule">
                      {['host class', 'answers at confidence ≥', 'calibration cases', 'error bound'].map((h, k) => (
                        <th key={h} className={`eyebrow py-1 ${k ? 'text-right pl-3' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(pol.threshold_map as Record<string, number>)
                      // plain-class fallbacks duplicate the fitted 'class|actor' rows
                      .filter(([k]) => !(k !== '*' && !k.includes('|')
                        && Object.keys(pol.threshold_map).some((o) => o.startsWith(`${k}|`))))
                      .map(([k, thr]) => {
                      const c = pol.by_class?.[k];
                      const never = thr > 1;
                      const [base, actor] = k.split('|');
                      return (
                        <tr key={k} className="border-b border-rule-soft last:border-0">
                          <td className="mono text-2xs py-1">
                            {k === '*' ? 'any other' : base}
                            {actor && <span className="text-ink-dim"> · {actor === 'shared' ? 'actor seen via exits' : 'actor direct'}</span>}
                          </td>
                          <td className="num mono text-2xs py-1"
                              style={never ? { color: 'var(--confirm)' } : undefined}>
                            {never ? (SHARED_EXITS.has(base) ? 'never · shared exit'
                              : actor === 'shared' ? 'never · usually a relay' : 'never · cannot bound')
                              : thr.toFixed(2)}
                          </td>
                          <td className="num mono text-2xs py-1">{c ? int(c.n_calibration) : '—'}</td>
                          <td className="num mono text-2xs py-1">
                            {c && c.attainable ? pct(c.risk_upper_bound) : '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </>
            )}
            {fixed && o && (
              <p className="text-sm text-ink-soft mt-2">
                The hand-set cut-off it replaces ({fixed.threshold}) answered{' '}
                <b className="mono">{int(fixed.outcomes.correct)}</b> correctly and withheld{' '}
                <b className="mono">{int(fixed.outcomes.unnecessary_abstain)}</b> whose origin had been
                observed. The fitted policy answers <b className="mono">{int(o.correct)}</b> correctly
                for <b className="mono">{int(o.wrong)}</b> wrong. VPN, Tor and CDN exits are never
                attributed: the address belongs to the provider, not the person.
              </p>
            )}
          </Panel>
          );
        })()}

        {m.sensitivity && (
          <Panel>
            <Eyebrow layer="network">attribution vs observation coverage</Eyebrow>
            <SensitivityCurve rows={m.sensitivity.curve} />
            <p className="text-sm text-ink-soft mt-2">
              Only observation coverage changes between points.{' '}
              {(() => {
                const rows: any[] = m.sensitivity.curve || [];
                const below = rows.filter((r) => r.top1_accuracy < chanceOf(r));
                if (below.length) return (
                  <>At <b className="mono">{below.map((r) => pc(r.coverage)).join(', ')}</b> coverage
                  the engine is <i>worse than guessing</i>: it mostly sees relays, not origins.</>
                );
                const lo = rows[0];
                return (
                  <>It beats guessing at every coverage. At {lo && pc(lo.coverage)} it answers only{' '}
                  <b className="mono">{lo?.attempt_rate != null ? pc(lo.attempt_rate) : '—'}</b> —
                  thin coverage costs abstentions, not wrong names.</>
                );
              })()}
            </p>
          </Panel>
        )}
      </div>

      {(met.attribution?.risk_coverage?.curve || test.calibration_study) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {met.attribution?.risk_coverage?.curve && (
            <Panel>
              <Eyebrow layer="network" right="test fold">attribution — error rate as coverage grows</Eyebrow>
              <RiskCoverageCurve curve={met.attribution.risk_coverage.curve}
                                 aurc={met.attribution.risk_coverage.aurc}
                                 eaurc={met.attribution.risk_coverage.e_aurc}
                                 target={met.attribution.policy?.target_risk} />
              <p className="text-sm text-ink-soft mt-2">
                Most-confident answers first; the curve ends at the{' '}
                <b className="mono">{pc(met.attribution.risk_coverage.max_coverage ?? 1)}</b> answered.{' '}
                {(() => {
                  const rc = met.attribution.risk_coverage;
                  const target = met.attribution.policy?.target_risk;
                  if (target === undefined) return null;
                  const over = (rc.curve as any[]).find((p) => p.coverage > 0.05 && p.risk > target);
                  return over
                    ? <>Error passes the {target} target at <b className="mono">{pc(over.coverage)}</b> coverage.</>
                    : <>Error stays under the {target} target the whole way.</>;
                })()}
              </p>
            </Panel>
          )}
          {test.calibration_study && (() => {
            const cs = test.calibration_study;
            const after = cs.after_prior_shift;
            return (
              <Panel>
                <Eyebrow layer="fusion" right="test fold">calibration at a different base rate</Eyebrow>
                <p className="text-sm text-ink-soft mb-2">
                  The calibration fold is <b className="mono">{pct(cs.calibration_fold_prior)}</b> illicit;
                  this test fold is <b className="mono">{pct(cs.test_prior_true)}</b>, estimated without
                  labels as <b className="mono">{pct(cs.test_prior_em_estimate)}</b>.
                </p>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-rule">
                      {['top k', 'as calibrated', 'after prior shift', 'observed'].map((h, k) => (
                        <th key={h} className={`eyebrow py-1 ${k ? 'text-right pl-3' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cs.before.top_k.map((r: any, k: number) => (
                      <tr key={r.k} className="border-b border-rule-soft">
                        <td className="mono text-2xs py-1">{r.k}</td>
                        <td className="num mono text-2xs py-1">{pct(r.mean_predicted)}</td>
                        <td className="num mono text-2xs py-1">{pct(after.top_k[k]?.mean_predicted)}</td>
                        <td className="num mono text-2xs py-1 font-semibold">{pct(r.observed_precision)}</td>
                      </tr>
                    ))}
                    <tr className="border-b border-rule-soft">
                      <td className="text-2xs py-1.5">calibration error (ECE)</td>
                      <td className="num mono text-2xs py-1.5">{pct(cs.before.ece)}</td>
                      <td className="num mono text-2xs py-1.5 font-semibold"
                          style={{ color: 'var(--confirm)' }}>{pct(after.ece)}</td>
                      <td />
                    </tr>
                    {cs.venn_abers && (
                      <tr title="score deciles where the Venn-Abers probability range meets the 95% interval of what actually happened">
                        <td className="text-2xs py-1.5">ranges consistent with outcomes</td>
                        <td className="num mono text-2xs py-1.5">
                          {cs.venn_abers.bins_inside} / {cs.venn_abers.bins.length}
                        </td>
                        <td className="num mono text-2xs py-1.5 font-semibold">
                          {cs.venn_abers.bins_inside_after_prior_shift ?? '—'} / {cs.venn_abers.bins.length}
                        </td>
                        <td />
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="text-sm text-ink-soft mt-2">
                  The queue shows the corrected probability, re-estimated for every capture.
                </p>
              </Panel>
            );
          })()}
        </div>
      )}

      {met.transaction_level && met.transaction_level.pr_auc !== undefined && (
        <Panel>
          <Eyebrow layer="chain"
                   right={`${Number(met.transaction_level.n_transactions).toLocaleString()} transactions`}>
            transaction-level head — "why a wallet/transaction was flagged"
          </Eyebrow>
          <table className="w-full">
            <tbody>
              <Row label="PR-AUC" value={pct(met.transaction_level.pr_auc)} layer="chain"
                   note={`base rate ${pct(met.transaction_level.baseline_pr_auc)}`} />
              <Row label="Precision @ 50" value={pct(met.transaction_level.precision_at_50)} />
              {met.transaction_level.classification && (
                <Row label="F1" value={pct(met.transaction_level.classification.f1)} />
              )}
            </tbody>
          </table>
          <p className="text-sm text-ink-soft mt-2">
            A second model over transaction features and the parent entity's score, split on
            the entity's fold.
          </p>
        </Panel>
      )}

      {(met.failure_gallery || []).length > 0 && (
        <Panel accent="danger">
          <Eyebrow layer="danger">failure gallery — cases we get wrong</Eyebrow>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {met.failure_gallery.slice(0, 6).map((f: any) => (
              <div key={f.entity + f.kind} className="bg-surface-2 p-3">
                <div className="flex items-center gap-2 mb-1">
                  <Tag layer={f.kind === 'false_positive' ? 'fusion' : 'network'}>
                    {f.kind.replace('_', ' ')}
                  </Tag>
                  <span className="mono text-sm font-semibold">{f.entity}</span>
                  <span className="mono text-2xs text-ink-dim ml-auto">score {pct(f.score)}</span>
                </div>
                <div className="mono text-2xs text-ink-dim mb-1">
                  truth: {f.archetype}{f.typology ? ` · ${f.typology}` : ''}
                </div>
                <p className="text-sm text-ink-soft">{f.why}</p>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {m.external && (
        <Panel accent={m.external.available ? 'confirm' : 'data'}>
          <Eyebrow layer="confirm">external validation — real labelled Bitcoin data</Eyebrow>
          {m.external.available ? (
            <>
              <div className="flex items-end gap-4 mb-2">
                <div>
                  <div className="font-cond font-bold text-3xl leading-none">
                    {pct(m.external.f1)}
                  </div>
                  <div className="mono text-2xs text-ink-dim">illicit-class F1 (Elliptic)</div>
                </div>
                <div className="mono text-sm text-ink-soft pb-1">
                  PR-AUC {pct(m.external.pr_auc)} ·
                  {' '}{Number(m.external.n_labelled).toLocaleString()} labelled nodes ·
                  {' '}positive rate {pct(m.external.positive_rate)}
                </div>
              </div>
              <p className="text-sm text-ink-soft">
                Published reference: {m.external.published_reference.source} reports
                illicit-class F1 ≈ {m.external.published_reference.illicit_f1} for
                {' '}{m.external.published_reference.model}; splits and feature subsets differ.
                {' '}Chain side only: Elliptic has no IP, port or timing data.
              </p>
            </>
          ) : (
            <p className="text-sm text-ink-soft">{m.external.note}</p>
          )}
        </Panel>
      )}

      {m.elliptic_pp?.available && (() => {
        const w = m.elliptic_pp.wallet_classification;
        const c = m.elliptic_pp.cospend_clustering;
        return (
          <Panel>
            <Eyebrow layer="confirm" right="Elliptic++ · KDD'23">
              external validation — at the actor level we actually ship
            </Eyebrow>
            <p className="text-sm text-ink-soft mb-3">
              {Number(w.n_labelled_addresses).toLocaleString()} labelled wallet addresses test the
              unit we score and the clustering that produces it.
            </p>
            <table className="w-full">
              <tbody>
                <Row label="address PR-AUC" value={pct(w.headline_address_disjoint.pr_auc)}
                     layer="fusion"
                     note={`base rate ${pct(w.headline_address_disjoint.positive_rate)} · ${Number(w.headline_address_disjoint.n).toLocaleString()} test addresses`} />
                <Row label="address F1" value={pct(w.headline_address_disjoint.f1)} layer="fusion"
                     note={`split is address-disjoint; the naive figure keeping repeats is ${pct(w.naive_repeated_addresses.f1)}`} />
                <Row label="co-spend clusters share a label"
                     value={pct(c.label_agreement.macro)} layer="confirm"
                     note={`vs ${pct(c.label_agreement_shuffled_control.macro)} label-shuffle control · lift ${c.lift_macro}×`} />
                <Row label="largest cluster, real Bitcoin"
                     value={Number(c.largest_entity_addresses_all).toLocaleString()}
                     layer="danger"
                     note={`${Number(met.entity_resolution?.largest_entity_addresses ?? 0).toLocaleString()} in our synthetic data — the supercluster collapse our generator does not reproduce`} />
              </tbody>
            </table>
            <p className="text-sm text-ink-soft mt-3">{m.elliptic_pp.scope}</p>
          </Panel>
        );
      })()}

      {R.elliptic_pp_ladder && (() => {
        const L = R.elliptic_pp_ladder;
        const rows: any[] = L.ladder || [];
        const r0 = rows[0], r2 = rows.find((r) => r.rung.startsWith('R2'));
        return (
          <Panel accent="danger">
            <Eyebrow layer="danger" right="re-run from the authors' notebook">
              Elliptic++ — where the published {L.upstream.published.f1} comes from
            </Eyebrow>
            <div className="overflow-x-auto scroll-hint">
              <table className="w-full min-w-[40rem]">
                <thead>
                  <tr className="border-b border-rule">
                    {['protocol', 'illicit F1', 'PR-AUC', 'test illicit rate'].map((h, k) => (
                      <th key={h} className={`eyebrow py-1 ${k ? 'text-right pl-3' : 'text-left'}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.rung} className="border-b border-rule-soft last:border-0"
                        style={r.rung.startsWith('OURS') ? { background: 'var(--fusion-wash)' } : undefined}>
                      <td className="text-sm py-1.5 pr-3">{r.rung}</td>
                      <td className="num mono text-sm py-1.5 font-semibold">{pct(r.f1)}</td>
                      <td className="num mono text-sm py-1.5">{pct(r.pr_auc)}</td>
                      <td className="num mono text-2xs py-1.5">{pct(r.test_positive_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-sm text-ink-soft mt-2 max-w-[95ch]">
              The published notebook splits by row position, not time, so{' '}
              <b className="mono">{pc(r0?.test_share_p2sh_addresses ?? 0)}</b> of test rows are P2SH. As
              coded it scores <b className="mono">{pct(r0?.f1)}</b>; under the paper's temporal split,{' '}
              <b className="mono">{pct(r2?.f1)}</b>. Ours are reported under the temporal split.
            </p>
          </Panel>
        );
      })()}

      {(R.faithfulness_demo || R.transfer || R.gnn_baseline) && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {R.faithfulness_demo && (() => {
            const f = R.faithfulness_demo;
            const d = f.deletion, mech = f.mechanism_agreement;
            const counts: Record<string, number> = {};
            Object.values(mech?.per_typology || {}).forEach((t: any) =>
              (t.most_common_top_features || []).forEach((x: any) => {
                counts[x.feature] = (counts[x.feature] || 0) + x.rows;
              }));
            const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k]) => k);
            return (
              <Panel>
                <Eyebrow layer="fusion" right="demo artefact">do the explanations mean anything?</Eyebrow>
                <table className="w-full">
                  <tbody>
                    <Row label="Score lost removing the top SHAP features" value={pct(d.aopc_shap)}
                         layer="confirm" note={`vs ${pct(d.aopc_random)} removing random features · AOPC over ${d.n_rows} leads`} />
                    <Row label="Top-3 features name the planted mechanism" value={pct(mech.hit_rate)}
                         layer="danger"
                         note={`chance ${pct(mech.chance_rate)} · label-permutation control ${pct(mech.permutation_control_mean)}`} />
                  </tbody>
                </table>
                <p className="text-sm text-ink-soft mt-2">
                  Faithful to the model, but it rarely rests on the planted mechanism (
                  {mech.hit_rate < mech.permutation_control_mean ? 'below' : 'above'} control). Most often:{' '}
                  <b className="mono">{top.join(', ')}</b>.
                </p>
              </Panel>
            );
          })()}

          {R.transfer && (() => {
            const rows: any[] = R.transfer.rows || [];
            const get = (a: string, b: string, f: string) =>
              rows.find((r) => r.trained_on === a && r.scored_on === b && r.features === f)?.pr_auc;
            const pairs = [...new Set(rows.map((r) => `${r.trained_on}|${r.scored_on}`))].map((k) => k.split('|'));
            return (
              <Panel>
                <Eyebrow layer="chain" right="test-fold PR-AUC">does it work on a capture it never saw?</Eyebrow>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-rule">
                      {['trained → scored', 'with graph embedding', 'without'].map((h, k) => (
                        <th key={h} className={`eyebrow py-1 ${k ? 'text-right pl-3' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pairs.map(([a, b]) => {
                      const w = get(a, b, 'with_embeddings'), wo = get(a, b, 'without_embeddings');
                      return (
                        <tr key={a + b} className="border-b border-rule-soft last:border-0">
                          <td className="mono text-2xs py-1">{a} → {b}{a === b ? '' : ' · new capture'}</td>
                          <td className="num mono text-2xs py-1"
                              style={w < wo ? { color: 'var(--danger)' } : undefined}>{pct(w)}</td>
                          <td className="num mono text-2xs py-1"
                              style={wo < w ? { color: 'var(--danger)' } : undefined}>{pct(wo)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <p className="text-sm text-ink-soft mt-2">
                  The embedding helps only on the capture it was fitted to. Red marks the worse of each pair.
                  {met.embeddings?.backend === 'disabled' && ' Shipped without it.'}
                </p>
              </Panel>
            );
          })()}

          {R.gnn_baseline && (() => {
            const g = R.gnn_baseline;
            const rows: [string, any][] = [
              ['random forest, 50 trees', g.random_forest_50], ['our gradient-boosted model', g.our_gbt],
              ['SIGN features + our model', g.sign_gbt], ['SGC, 2-hop', g.sgc_2hop],
              [g.graphsage?.runs ? `GraphSAGE · ${g.graphsage.runs.length} seeds` : 'GraphSAGE', g.graphsage],
            ];
            return (
              <Panel>
                <Eyebrow layer="confirm" right="Elliptic · strict inductive">graph networks vs trees</Eyebrow>
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-rule">
                      {['model', 'F1', 'PR-AUC'].map((h, k) => (
                        <th key={h} className={`eyebrow py-1 ${k ? 'text-right pl-3' : 'text-left'}`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(([k, v]) => (
                      <tr key={k} className="border-b border-rule-soft last:border-0">
                        <td className="text-2xs py-1">{k}</td>
                        {v && v.available !== false ? (
                          <>
                            {(['f1', 'pr_auc'] as const).map((m) => (
                              <td key={m} className="num mono text-2xs py-1">
                                {v.mean_std
                                  ? <>{pct(v.mean_std[m][0])}<span className="text-ink-dim"> ±{v.mean_std[m][1].toFixed(3)}</span></>
                                  : pct(v[m])}
                              </td>
                            ))}
                          </>
                        ) : (
                          <td colSpan={2} className="text-right py-1"><Unmeasured /></td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-sm text-ink-soft mt-2">
                  Train steps 1–34, test 35–49 on an unseen graph.{' '}
                  {g.random_forest_50?.f1 > g.our_gbt?.f1 && (
                    <>Random forest wins on F1; ours ranks {g.our_gbt.pr_auc >= g.random_forest_50.pr_auc ? 'slightly better' : 'worse'} (PR-AUC).{' '}</>
                  )}
                  Graph models trail the trees.
                </p>
              </Panel>
            );
          })()}
        </div>
      )}

      <Panel>
        <Eyebrow layer="network" right="real network · our own transactions only">
          what a network observer can and cannot see
        </Eyebrow>
        {(() => {
          const tb = R.testbed_mainnet, wire = R.wire_observer;
          const access: [string, string][] = [
            ['hosting', 'cloud-hosted node'], ['residential', 'home broadband'], ['mobile', 'mobile hotspot'],
            ['vpn', 'behind a VPN'], ['tor', 'over Tor'], ['private_broadcast', 'private broadcast (Core PR #29415)'],
          ];
          const cell = (v: any) => v?.rate != null
            ? <span className="mono">{pct(v.rate)} <span className="text-ink-dim">[{v.wilson_95?.map(pct).join('–')}]</span></span>
            : <Unmeasured />;
          if (!tb && !wire) return (
            <p className="text-sm text-ink-soft">
              Not yet measured on a live network. Every attribution figure on this page comes from simulated captures.
            </p>
          );
          return (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-rule">
                    <th className="eyebrow py-1 text-left">origin of the transaction</th>
                    <th className="eyebrow py-1 text-right" style={{ color: 'var(--network)' }}>
                      first announcer is the sender
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {access.map(([k, label]) => (
                    <tr key={k} className="border-b border-rule-soft last:border-0">
                      <td className="text-sm py-1.5">{label}</td>
                      <td className="text-right text-2xs py-1.5">{cell(tb?.by_access?.[k])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-rule">
                    <th className="eyebrow py-1 text-left">peer connection</th>
                    <th className="eyebrow py-1 text-right" style={{ color: 'var(--network)' }}>
                      announcement visible in encrypted traffic
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[['v1', 'plaintext (v1)'], ['v2', 'encrypted, BIP324 (v2)']].map(([k, label]) => (
                    <tr key={k} className="border-b border-rule-soft last:border-0">
                      <td className="text-sm py-1.5">{label}</td>
                      <td className="text-right text-2xs py-1.5">
                        {wire?.[k]?.pr_auc != null
                          ? <span className="mono">PR-AUC {pct(wire[k].pr_auc)} <span className="text-ink-dim">base {pct(wire[k].positive_rate)}</span></span>
                          : <Unmeasured />}
                      </td>
                    </tr>
                  ))}
                  <tr className="border-b border-rule-soft last:border-0">
                    <td className="text-sm py-1.5">wallet with no node of its own</td>
                    <td className="text-right py-1.5"><Unmeasured /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          );
        })()}
      </Panel>

      {/* The fusion weights are a trade-off, so show the curve they sit on. */}
      {(met.fusion_sweep || []).length > 0 && (
        <Panel>
          <Eyebrow layer="fusion" right="measured on the test + held-out folds">
            fusion trade-off — why these weights
          </Eyebrow>
          <div className="overflow-x-auto">
            <div className="overflow-x-auto scroll-hint">
            <table className="w-full min-w-[46rem]">
              <thead>
                <tr className="border-b border-rule">
                  {['supervised', 'novelty', 'evidence', 'test PR-AUC', 'P@10', 'P@50',
                    'held-out recall', ''].map((h, i) => (
                    <th key={h + i} className={`eyebrow py-2 ${i >= 3 && i < 7 ? 'text-right' : 'text-left'}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {met.fusion_sweep.map((f: any, i: number) => (
                  <tr key={i}
                      className="border-b border-rule-soft last:border-0"
                      style={f.shipped ? { background: 'var(--fusion-wash)' } : undefined}>
                    <td className="mono text-sm py-2">{f.supervised.toFixed(2)}</td>
                    <td className="mono text-sm py-2">{f.novelty.toFixed(2)}</td>
                    <td className="mono text-sm py-2">{f.evidence.toFixed(2)}</td>
                    <td className="num mono text-sm py-2">{pct(f.test_pr_auc)}</td>
                    <td className="num mono text-sm py-2">{pct(f.precision_at_10)}</td>
                    <td className="num mono text-sm py-2">{pct(f.precision_at_50)}</td>
                    <td className="num mono text-sm py-2" style={{ color: 'var(--network)' }}>
                      {pct(f.holdout_recall)}
                    </td>
                    <td className="py-2 pl-3">
                      {f.shipped ? <Tag layer="fusion">shipped</Tag> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
          <p className="text-sm text-ink-soft mt-2 max-w-[95ch]">
            More novelty weight catches more unseen typologies at the cost of precision. We
            chose the precision end: an analyst's scarcest resource is time.
          </p>
        </Panel>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Panel>
          <Eyebrow layer="fusion" right="mean |SHAP|">most influential features</Eyebrow>
          <table className="w-full">
            <tbody>
              {Object.entries(met.feature_importance || {}).slice(0, 12).map(([f, v]: [string, any]) => (
                <tr key={f} className="border-b border-rule-soft last:border-0">
                  <td className="mono text-2xs py-1 w-52 truncate">{f}</td>
                  <td className="py-1"><Bar value={v} max={Math.max(
                    ...Object.values(met.feature_importance || {}).map(Number)) || 1}
                    width={130} height={9} /></td>
                  <td className="num mono text-2xs py-1 w-14">{(v * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel>
          <Eyebrow layer="data">split integrity &amp; behavioural clusters</Eyebrow>
          <table className="w-full mb-3">
            <thead>
              <tr className="border-b border-rule">
                {['fold', 'entities', 'illicit', 'rate'].map((h, i) => (
                  <th key={h} className={`eyebrow py-1 ${i ? 'text-right' : 'text-left'}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(met.splits || {}).map(([k, v]: [string, any]) => (
                <tr key={k} className="border-b border-rule-soft last:border-0">
                  <td className="mono text-2xs py-1">{k}</td>
                  <td className="num mono text-2xs py-1">{Number(v.n).toLocaleString()}</td>
                  <td className="num mono text-2xs py-1">{Number(v.n_illicit).toLocaleString()}</td>
                  <td className="num mono text-2xs py-1">{(v.illicit_rate * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-sm text-ink-soft">
            Entity-grouped, temporally forward splits. HDBSCAN found{' '}
            <b className="mono">{met.behavioural_clusters?.n_clusters ?? 0}</b> unlabelled archetypes;{' '}
            <b className="mono">{((met.behavioural_clusters?.noise_fraction ?? 0) * 100).toFixed(0)}%</b>{' '}
            of entities fit none.
          </p>
        </Panel>
      </div>
    </div>
  );
}
