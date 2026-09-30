/** Three ways to present the same sixty leads.
 *
 * The queue is the screen this whole system exists to produce, and there is no
 * single obviously-right shape for it: a table compares well and reads badly, a
 * document reads well and compares badly, and a demo wants neither. Rather than
 * argue about it, all three are built and switchable, against real data.
 *
 * They share the data and the semantics - rank, evidence composition, the
 * written narrative, attribution, magnitude - and differ only in what they make
 * easy. Pick by what the screen is for, then delete the other two.
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, CASE_TIP, fmt, watchlistPhrase, type Alert, type CaseFile, type WatchlistHit } from '../api';
import { GraphView } from './GraphView';
import { ReasonChooser } from './ReasonChooser';
import { featureLabel, featureValue } from '../featureLabels';
import { Button, Eyebrow, Tag, layerColor, layerWash } from '../ui';

/** Evidence composition as three present/absent marks.
 *
 * Chain corroboration, a resolved network identity, the model's own call. The
 * point is what it shows when you scan the column rather than one lead: on a
 * typical run the middle mark lights up two or three times in sixty, so the
 * engine's refusal to name an owner becomes visible rather than implied.
 */
export function Evidence({ a, size = 'sm' }: { a: Alert; size?: 'sm' | 'lg' }) {
  const w = size === 'lg' ? 'w-2.5 h-5' : 'w-2 h-4';
  const cells: [string, boolean, string][] = [
    ['--chain', Boolean(a.typologies),
     a.typologies
       ? `chain: ${a.typologies.split('|').filter(Boolean).map(fmt.typology).join(', ')}`
       : 'chain: no named typology matched'],
    ['--network', a.attribution_status === 'ok' && Boolean(a.top_asn),
     a.attribution_status === 'ok' && a.top_asn
       ? `network: attributed to AS${a.top_asn}`
       : 'network: every candidate IP was shared infrastructure — suppressed, not guessed'],
    ['--fusion', true,
     a.raised_by === 'novelty'
       ? 'model: raised by the novelty detector, not the classifier'
       : 'model: ranked by the trained classifier'],
  ];
  return (
    <span className="inline-flex items-center gap-1 align-middle" role="img"
          aria-label={cells.map(([, on, t]) => (on ? t : `no ${t}`)).join('. ')}>
      {cells.map(([layer, on, title]) => (
        <span key={layer} title={title} className={`${w} inline-block`}
              style={on ? { background: `var(${layer})` }
                        : { boxShadow: 'inset 0 0 0 1px var(--rule)' }} />
      ))}
    </span>
  );
}

/** Attribution, or the reason there isn't one. */
function Attribution({ a, prose = false }: { a: Alert; prose?: boolean }) {
  const ok = a.attribution_status === 'ok' && Boolean(a.top_asn);
  if (ok) {
    return (
      <span className="whitespace-nowrap">
        <span className="mono text-md font-semibold text-network">AS{a.top_asn}</span>
        <span className="text-2xs text-ink-soft ml-2">
          {a.top_asn_type} · {a.top_country} · <span className="mono">{fmt.conf(a.attribution_confidence)}</span>
        </span>
      </span>
    );
  }
  return prose ? (
    <span className="text-sm text-ink-soft">
      Suppressed — every candidate IP was shared infrastructure.
    </span>
  ) : (
    <span className="text-sm text-ink-dim whitespace-nowrap"
          title="Every candidate IP resolved to shared infrastructure. Suppressed rather than guessed.">
      <span aria-hidden className="text-rule">—</span> no owner named
    </span>
  );
}

const logMag = (v: number, max: number) =>
  max > 1 ? Math.log10(Math.max(v, 1)) / Math.log10(max) : 0;

/** The half of the narrative that is actually about THIS entity.
 *
 * The text is templated from the feature vector, so its opening is shared: on a
 * sampled run twelve consecutive leads had identical first seventy characters,
 * which turned a grid of cards into a wall of the same paragraph. The closing
 * sentence carries the announcing host - a different IP, ASN and country per
 * lead - so that is what a card shows.
 */
function splitNarrative(narrative: string): { body: string; origin: string } {
  const parts = (narrative || '').split(/(?<=\.)\s+/).filter(Boolean);
  const last = parts[parts.length - 1] || '';
  if (/announced from/i.test(last)) {
    return { body: parts.slice(0, -1).join(' '), origin: last };
  }
  return { body: narrative || '', origin: '' };
}

/* ═══════════════════════════════ B · DOSSIER ══════════════════════════════ */

/** One scrolling column of written cases. Optimised for reading, not comparing.
 *
 * The rank sits in the margin the way a figure number does, the entity is a
 * heading, and the narrative is set as prose at a real measure. It is a stack of
 * short intelligence products rather than a grid of values - which is what the
 * data actually is, and what a table could never show.
 */
export function DossierView({ rows, maxValue, onOpen, near }: {
  rows: Alert[]; maxValue: number; onOpen: (e: string) => void;
  near?: Map<string, WatchlistHit>;
}) {
  const stat = (label: string, value: ReactNode, layer?: string) => (
    <div>
      <div className="colhead">{label}</div>
      <div className="mono text-sm font-semibold mt-0.5"
           style={layer ? { color: `var(${layer})` } : undefined}>{value}</div>
    </div>
  );
  const fact = (label: string, value: ReactNode) => (
    <div>
      <div className="colhead">{label}</div>
      <div className="text-sm text-ink mt-0.5">{value}</div>
    </div>
  );
  return (
    <div>
      {rows.map((a, i) => (
        <article key={a.entity}
                 style={{ animationDelay: `${Math.min(i, 10) * 26}ms` }}
                 className="anim-rise border-b border-rule-soft px-6 py-6
                            hover:bg-surface-2 transition-colors duration-150">
          <div className="flex flex-wrap lg:flex-nowrap gap-6">
            <div className="w-14 shrink-0 text-right pt-1">
              <div className={`mono ${a.rank <= 3 ? 'text-4xl font-semibold text-ink' : 'text-xl text-ink-dim'}`}
                   style={{ lineHeight: 1 }}>{a.rank}</div>
              <div className="mt-3 flex justify-end"><Evidence a={a} size="lg" /></div>
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-3 flex-wrap">
                <h3 className="mono text-xl font-semibold text-ink">{a.entity}</h3>
                <div className="ml-auto flex gap-1 flex-wrap">
                  {a.raised_by === 'novelty' && <Tag layer="network">novelty slot</Tag>}
                  {(a.typologies || '').split('|').filter(Boolean)
                    .map((t) => <Tag key={t} layer="fusion">{fmt.typology(t)}</Tag>)}
                </div>
              </div>

              {(() => {
                const { body, origin: from } = splitNarrative(a.narrative);
                return (
                  <>
                    <p className="text-base text-ink leading-relaxed mt-3 max-w-[74ch]">{body}</p>
                    {from && (
                      <p className="text-base leading-relaxed mt-2 max-w-[74ch] text-network">
                        {from}
                      </p>
                    )}
                  </>
                );
              })()}

              <div className="flex flex-wrap items-end gap-x-8 gap-y-3 mt-4">
                {stat('value moved', fmt.btc(a.total_out), '--chain')}
                {stat('addresses', fmt.int(a.n_addresses))}
                {stat('transactions', fmt.int(a.n_tx))}
                {stat('announcing IPs', fmt.int(a.n_ips), '--network')}
                {stat('novelty', fmt.conf(a.novelty), '--network')}
              </div>

              <div className="h-1 bg-surface-3 mt-4 max-w-[74ch]">
                <div className="h-full" style={{ width: `${Math.max(3, logMag(a.total_out, maxValue) * 100)}%`,
                                                 background: 'var(--chain)' }} />
              </div>
            </div>

            {/* The facts an analyst decides on, beside the prose instead of
                under it, so the right of the card is not dead space. */}
            <aside className="grid grid-cols-2 content-start gap-x-6 gap-y-3 w-full
                              lg:w-[26rem] xl:w-[30rem] shrink-0 lg:pl-6 lg:border-l border-rule-soft">
              {fact('confidence', <span className="mono text-md font-semibold text-fusion">
                {fmt.conf(a.confidence)}{' '}
                <span className="text-2xs font-normal text-ink-soft">{fmt.range(a.confidence, a.interval)}</span>
              </span>)}
              {fact('raised by', a.raised_by === 'novelty' ? 'novelty detector' : 'trained classifier')}
              {fact('attribution', a.attribution_status === 'ok' && a.top_asn
                ? <span><span className="mono font-semibold text-network">AS{a.top_asn}</span>
                    <span className="text-ink-soft"> · {a.top_asn_type} · {a.top_country}</span></span>
                : <span className="text-ink-dim">suppressed — shared infrastructure</span>)}
              {a.case_id ? fact('case', <span title={CASE_TIP}>
                <span className="mono font-semibold text-fusion">{a.case_id}</span>
                {a.n_linked_entities
                  ? ` · ${fmt.int(a.n_linked_entities)} linked actor${a.n_linked_entities > 1 ? 's' : ''}`
                  : ' · single actor'}
              </span>) : null}
              {near?.get(a.entity) ? fact('watchlist', <span className="text-danger">
                {watchlistPhrase(near.get(a.entity)!)}</span>) : null}
              {fact('verdict', a.verdict
                ? <span style={{ color: a.verdict === 'confirmed' ? 'var(--confirm)' : 'var(--ink-soft)' }}>{a.verdict}</span>
                : <span className="text-ink-dim">not reviewed</span>)}
              <div className="col-span-2 pt-1">
                <Button variant="ghost" onClick={() => onOpen(a.entity)}>open case file</Button>
              </div>
            </aside>
          </div>
        </article>
      ))}
    </div>
  );
}

/* ════════════════════════════════ C · FOCUS ═══════════════════════════════ */

/** One lead, the whole width. Built for the moment somebody is watching.
 *
 * A queue is the wrong object to put in front of an audience - sixty rows of
 * anything is a wall. This shows a single case at presentation size and moves
 * through them with the arrow keys, so the person talking controls exactly what
 * the room is looking at.
 */
export function FocusView({ rows, index, onIndex, onOpen, onVerdict }: {
  rows: Alert[]; index: number;
  onIndex: (i: number) => void; onOpen: (e: string) => void;
  onVerdict: (e: string, v: string, reason?: string) => void;
}) {
  const a = rows[Math.min(index, rows.length - 1)];
  const [pending, setPending] = useState<'confirmed' | 'dismissed' | null>(null);

  // One lead on screen means one lead's worth of detail is affordable. The
  // narrative is templated - measured: twelve consecutive leads share the same
  // opening seventy characters - so the thing that actually distinguishes this
  // entity from the next one is its SHAP decomposition and its evidence chain,
  // and both need a fetch. Debounced, so holding an arrow key does not queue
  // sixty of them.
  const [detail, setDetail] = useState<CaseFile | null>(null);
  const entity = a?.entity;
  useEffect(() => {
    if (!entity) return;
    let live = true;
    setDetail(null);
    const t = setTimeout(() => {
      api.caseFile(entity).then((d) => live && setDetail(d)).catch(() => {});
    }, 220);
    return () => { live = false; clearTimeout(t); };
  }, [entity]);

  if (!a) return null;

  const big = (label: string, value: ReactNode, layer?: string) => (
    <div>
      <div className="colhead">{label}</div>
      <div className="mono text-xl font-semibold mt-1"
           style={layer ? { color: `var(${layer})` } : undefined}>{value}</div>
    </div>
  );

  const shap = (detail?.shap ?? []).slice(0, 5);
  const shapMax = Math.max(1e-6, ...shap.map((r) => Math.abs(r.contribution)));

  return (
    <div className="px-8 py-6">
      {/* Position in the queue as a scrubbable strip, coloured by what evidence
          backs each lead - so the shape of the whole run is legible at a glance
          and any lead is one click away. */}
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" disabled={index <= 0} onClick={() => onIndex(index - 1)}>
          ← previous
        </Button>
        <span className="mono text-2xs text-ink-dim whitespace-nowrap">
          lead <span className="text-ink font-semibold">{index + 1}</span> of {rows.length}
        </span>
        <Button variant="ghost" disabled={index >= rows.length - 1}
                onClick={() => onIndex(index + 1)}>next →</Button>
        <div className="flex-1 flex items-center gap-px h-6 ml-3">
          {rows.map((r, i) => (
            <button key={r.entity} onClick={() => onIndex(i)}
                    title={`${r.rank} · ${r.entity} · ${fmt.btc(r.total_out)}${r.verdict ? ` · ${r.verdict}` : ''}`}
                    aria-label={`Go to lead ${r.rank}, ${r.entity}`}
                    className="flex-1 transition-all duration-150 cursor-pointer"
                    style={{
                      height: i === index ? '100%' : '62%',
                      background: r.verdict === 'confirmed' ? 'var(--confirm)'
                        : i === index ? 'var(--ink)'
                        : r.attribution_status === 'ok' && r.top_asn ? 'var(--network)'
                        : r.typologies ? 'var(--chain)' : 'var(--rule)',
                    }} />
          ))}
        </div>
      </div>

      <div className="flex items-baseline gap-4 flex-wrap">
        <span className="mono text-2xl text-ink-dim">#{a.rank}</span>
        <h2 className="display text-ink" style={{ fontSize: 'clamp(26px, 3.4vw, 46px)' }}>
          {a.entity}
        </h2>
        <Evidence a={a} size="lg" />
        <div className="ml-auto flex items-center gap-4">
          <div className="text-right">
            <div className="mono text-2xl font-semibold text-ink leading-none">
              {fmt.conf(a.confidence)}
            </div>
            <div className="mono text-2xs text-ink-soft mt-1">{fmt.range(a.confidence, a.interval)} calibrated</div>
          </div>
          {/* Triage without leaving the queue. The verdict is what the ranking
              learns from on the next run. */}
          {a.verdict
            ? <Tag layer={a.verdict === 'confirmed' ? 'confirm' : 'data'}
                   title={a.verdict_reason || undefined}>{a.verdict}</Tag>
            : (
              <div className="flex gap-2">
                <Button variant="ghost" onClick={() => setPending('confirmed')}>confirm</Button>
                <Button variant="ghost" onClick={() => setPending('dismissed')}>dismiss</Button>
              </div>
            )}
          {pending && (
            <ReasonChooser entity={a.entity} verdict={pending}
                           onCancel={() => setPending(null)}
                           onSave={(r) => { onVerdict(a.entity, pending, r); setPending(null); }} />
          )}
          <Button variant="default" onClick={() => onOpen(a.entity)}>open case file</Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mt-4">
        {a.raised_by === 'novelty' && <Tag layer="network">novelty slot</Tag>}
        {(a.typologies || '').split('|').filter(Boolean)
          .map((t) => <Tag key={t} layer="fusion">{fmt.typology(t)}</Tag>)}
      </div>

      <div className="flex flex-col xl:flex-row gap-6 2xl:gap-8 mt-5">
        <div className="flex-1 min-w-0">
          <p className="text-base text-ink leading-relaxed max-w-[70ch]">{a.narrative}</p>

          <div className="grid grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4 mt-6
                          pt-5 border-t border-rule-soft">
            {big('value moved', fmt.btc(a.total_out), '--chain')}
            {big('received', fmt.btc(a.total_in))}
            {big('addresses', fmt.int(a.n_addresses))}
            {big('transactions', fmt.int(a.n_tx))}
            {big('announcing IPs', fmt.int(a.n_ips), '--network')}
            {big('novelty', fmt.conf(a.novelty), '--network')}
          </div>

          {/* What the model actually keyed on, for THIS entity. Exact SHAP over
              a tree ensemble, not an approximation. */}
          <div className="mt-6 pt-5 border-t border-rule-soft">
            <div className="colhead">why the model scored it</div>
            {shap.length ? (
              <div className="mt-2 space-y-1.5 max-w-[46rem]">
                {shap.map((r) => (
                  <div key={r.feature} className="flex items-center gap-3">
                    <span className="text-sm text-ink w-72 shrink-0 truncate"
                          title={`${r.feature}${r.meaning ? ` - ${r.meaning}` : ''}`}>
                      {featureLabel(r.feature)}
                      <span className="mono text-2xs text-ink-dim"> · {featureValue(r.feature, r.value)}</span>
                    </span>
                    <div className="flex-1 h-2 bg-surface-3">
                      <div className="h-full" style={{
                        width: `${(Math.abs(r.contribution) / shapMax) * 100}%`,
                        background: r.direction === 'increases' ? 'var(--fusion)' : 'var(--confirm)',
                      }} />
                    </div>
                    <span className="mono text-2xs w-14 text-right"
                          style={{ color: r.direction === 'increases' ? 'var(--fusion)' : 'var(--confirm)' }}>
                      {r.contribution > 0 ? '+' : ''}{r.contribution.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="mt-2 text-sm text-ink-dim">reading attributions…</div>
            )}
          </div>

          <div className="mt-6 pt-5 border-t border-rule-soft">
            <div className="colhead">attribution</div>
            <div className="mt-1.5"><Attribution a={a} prose /></div>
          </div>

          {/* The transactions that prove it. An assertion with no TXID behind it
              is not evidence. */}
          {detail?.evidence?.length ? (
            <div className="mt-6 pt-5 border-t border-rule-soft">
              <div className="colhead">evidence chain</div>
              <div className="mt-2 space-y-3 max-w-[70ch]">
                {detail.evidence.slice(0, 3).map((e, i) => (
                  <div key={i}>
                    <div className="flex items-baseline gap-2">
                      <Tag layer="fusion">{fmt.typology(e.typology)}</Tag>
                      <span className="mono text-2xs text-ink-dim">
                        strength {fmt.conf(e.strength)}
                      </span>
                    </div>
                    <p className="text-sm text-ink-soft mt-1">{e.summary}</p>
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {(e.txids || []).slice(0, 4).map((t) => (
                        <span key={t} className="mono text-2xs text-chain border border-rule px-1.5 py-0.5"
                              title={t}>{t.slice(0, 16)}…</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        <div className="xl:w-[26rem] 2xl:w-[34rem] shrink-0">
          <div className="border border-rule bg-surface">
            <div className="px-3 pt-2"><Eyebrow layer="chain">link analysis</Eyebrow></div>
            <GraphView key={entity} entity={entity!} />
          </div>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════ D · TABLE ═════════════════════════════════ */

const mark = (d: ReactNode, w = 14) => (
  <svg viewBox="0 0 14 14" width={w} height={w} fill="none" stroke="currentColor"
       strokeWidth="1.5" strokeLinecap="square" aria-hidden>{d}</svg>
);
const SortDown = mark(<path d="M3.5 5l3.5 4 3.5-4" />, 11);
const SortNone = mark(<><path d="M4 6l3-3 3 3" /><path d="M4 8l3 3 3-3" /></>, 11);
const SortUp = mark(<path d="M3.5 9l3.5-4 3.5 4" />, 11);
const ChevronRight = mark(<path d="M5.5 3.5 9 7l-3.5 3.5" />, 12);

/* Column widths are declared here rather than inline because the ratios matter:
   typology previously took 338px - the widest column in the table - to hold two
   short tags, which pushed confidence and attribution into the right third and
   left a long empty gap for the eye to cross. */
type SortKey = 'rank' | 'confidence' | 'novelty' | 'total_out' | 'n_ips';

const COLUMNS: { key: string; label: string; align: string; width: string; sort?: SortKey }[] = [
  { key: 'rank',  label: 'rank',          align: 'text-right', width: 'w-20',  sort: 'rank' },
  { key: 'ev',    label: 'evidence',    align: 'text-left',  width: 'w-20' },
  { key: 'ent',   label: 'entity',      align: 'text-left',  width: 'w-56' },
  { key: 'typ',   label: 'pattern',     align: 'text-left',  width: 'w-52' },
  { key: 'attr',  label: 'attribution', align: 'text-left',  width: 'w-44' },
  { key: 'conf',  label: 'confidence',  align: 'text-right', width: 'w-28', sort: 'confidence' },
  { key: 'nov',   label: 'novelty',     align: 'text-right', width: 'w-16', sort: 'novelty' },
  { key: 'val',   label: 'value moved', align: 'text-right', width: 'w-48', sort: 'total_out' },
  { key: 'ver',   label: 'verdict',     align: 'text-left',  width: 'w-40' },
  { key: 'act',   label: '',            align: 'text-left',  width: 'w-8' },
];

/** The original queue, unchanged.
 *
 * Kept as a first-class option rather than deleted: a table is still the only
 * one of these that lets an analyst compare a value across sixty leads without
 * moving their eyes off a column, and that is a real job the other layouts do
 * badly. It carries the same evidence marks and log magnitude bars as the rest.
 */
export function TableView({ rows, maxValue, sort, onSort, onOpen, onVerdict, threshold, near }: {
  rows: Alert[]; maxValue: number; threshold: number;
  sort: { key: string; dir: 'asc' | 'desc' };
  onSort: (k: string) => void;
  onOpen: (e: string) => void;
  onVerdict: (e: string, v: string, reason?: string) => void;
  near?: Map<string, WatchlistHit>;
}) {
  const cursor = -1;
  const visible = rows;
  const toggleSort = onSort;
  const [pending, setPending] = useState<{ entity: string; verdict: 'confirmed' | 'dismissed' } | null>(null);
  return (
      <>
      {pending && (
        <ReasonChooser entity={pending.entity} verdict={pending.verdict}
                       onCancel={() => setPending(null)}
                       onSave={(r) => { onVerdict(pending.entity, pending.verdict, r); setPending(null); }} />
      )}
      <div className="overflow-x-auto scroll-hint">
        <table className="w-full border-collapse min-w-[70rem]">
          <thead>
            <tr className="border-b border-rule">
              {COLUMNS.map((c) => (
                <th key={c.key}
                    onClick={c.sort ? () => toggleSort(c.sort!) : undefined}
                    aria-sort={c.sort && sort.key === c.sort
                      ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                    className={`colhead px-3 py-2 ${c.align} ${c.width}
                      ${c.sort ? 'cursor-pointer select-none hover:text-ink' : ''}`}>
                  <span className="inline-flex items-center gap-1">
                    {c.label}
                    {c.sort ? (
                      <span className={sort.key === c.sort ? 'text-ink' : 'text-ink-dim opacity-45'}>
                        {sort.key === c.sort
                          ? (sort.dir === 'asc' ? SortUp : SortDown)
                          : SortNone}
                      </span>
                    ) : null}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((a, ri) => {
              const below = a.confidence < threshold;
              const typs = a.typologies ? a.typologies.split('|').filter(Boolean) : [];
              const attributed = a.attribution_status === 'ok' && Boolean(a.top_asn);
              // Log, because value moved spans 24,224x across this queue - four
              // and a half orders of magnitude. A linear bar would render
              // fifty-nine leads as an empty track and one as full.
              const mag = maxValue > 1
                ? Math.log10(Math.max(a.total_out, 1)) / Math.log10(maxValue)
                : 0;
              return (
                <tr key={a.entity}
                    onClick={() => onOpen(a.entity)}
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') onOpen(a.entity); }}
                    data-row={ri}
                    data-open={a.entity}
                    data-cursor={ri === cursor ? '1' : '0'}
                    style={{ animationDelay: `${Math.min(ri, 14) * 18}ms` }}
                    className={`anim-rise row-hover border-b border-rule-soft cursor-pointer
                      ${below ? 'opacity-50' : ''}
                      ${a.verdict === 'dismissed' ? 'opacity-40' : ''}
                      ${ri === cursor ? 'bg-chain-wash outline outline-1 -outline-offset-1 outline-chain' : ''}`}>

                  {/* Rank. The top three carry the model's strongest claim, so
                      they are the only ones set at size; below that the ordinal
                      is a reference, not a headline. */}
                  <td className="pl-3 pr-1 py-2.5 align-top num">
                    <span className={a.rank <= 3
                      ? 'mono text-lg font-semibold text-ink'
                      : 'mono text-sm text-ink-dim'}>{a.rank}</span>
                    {a.case_id && (
                      <div className="mono text-2xs text-ink-dim whitespace-nowrap mt-0.5"
                           title={a.n_linked_entities
                             ? `${CASE_TIP} ${a.n_linked_entities} linked actors.` : CASE_TIP}>
                        {a.case_id}
                      </div>
                    )}
                  </td>

                  <td className="px-3 py-2.5 align-top"><Evidence a={a} /></td>

                  {/* The identity, and what it is made of. This is the anchor of
                      the row: the one thing the analyst acts on. */}
                  <td className="px-3 py-2.5 align-top">
                    <div className="mono text-md font-semibold text-ink whitespace-nowrap
                                    flex items-center gap-2">
                      {a.entity}
                    </div>
                    <div className="text-2xs text-ink-dim whitespace-nowrap mt-0.5">
                      <span className="mono">{fmt.int(a.n_addresses)}</span> addr
                      <span aria-hidden className="text-rule"> · </span>
                      <span className="mono">{fmt.int(a.n_tx)}</span> tx
                      <span aria-hidden className="text-rule"> · </span>
                      <span className="mono">{fmt.int(a.n_ips)}</span> IP
                    </div>
                  </td>

                  {/* Pattern. Absent is the quiet case - a fifth of the queue has
                      no named typology, and a full tag on each made the widest
                      column a repeated statement about nothing. */}
                  <td className="px-3 py-2.5 align-top">
                    {near?.get(a.entity) && (
                      <div className="mb-1">
                        <Tag layer="danger" title={watchlistPhrase(near.get(a.entity)!)}>
                          {near.get(a.entity)!.hops === 0 ? 'watchlisted'
                            : `watchlist · ${near.get(a.entity)!.hops} hop${near.get(a.entity)!.hops > 1 ? 's' : ''}`}
                        </Tag>
                      </div>
                    )}
                    {a.raised_by === 'novelty' ? (
                      <Tag layer="network"
                           title="The classifier ranked this low; the novelty detector ranked it high. A reserved-slot alert — the answer to typologies nobody labelled.">
                        novelty slot
                      </Tag>
                    ) : typs.length ? (
                      <div className="flex flex-wrap gap-1">
                        {typs.map((t) => <Tag key={t} layer="fusion">{fmt.typology(t)}</Tag>)}
                      </div>
                    ) : (
                      <span className="text-sm text-ink-dim"
                            title="The classifier scored this highly on learned behaviour, but none of the six named laundering typologies matched. Open the case file for the SHAP reasons.">
                        model-only
                      </span>
                    )}
                  </td>

                  {/* Attribution. Three of sixty resolve, and this is the entire
                      thesis of the project landing on screen - so when it lands
                      it is the loudest thing in the row, and when it does not it
                      is the quietest. */}
                  <td className="px-3 py-2.5 align-top">
                    {attributed ? (
                      <div>
                        <div className="mono text-md font-semibold text-network whitespace-nowrap">
                          AS{a.top_asn}
                        </div>
                        <div className="text-2xs text-ink-soft whitespace-nowrap mt-0.5">
                          {a.top_asn_type} · {a.top_country} ·{' '}
                          <span className="mono">{fmt.conf(a.attribution_confidence)}</span>
                        </div>
                      </div>
                    ) : (
                      <span className="text-sm text-ink-dim"
                            title="Every candidate IP for this entity resolved to shared infrastructure. The engine suppressed the attribution rather than name someone on evidence that cannot carry it.">
                        <span aria-hidden className="text-rule">—</span>{' '}
                        {a.attribution_status === 'ok' ? 'no link' : 'suppressed'}
                      </span>
                    )}
                  </td>

                  {/* Confidence and its interval at the same weight. The
                      calibrator clips at 0.97, so 54 of 60 leads print 0.96 or
                      0.97 - measured - and the number that varies least used to
                      be the largest thing in the row. The interval spans
                      0.093-0.382 across the same queue, and that is the half
                      worth reading. */}
                  <td className="px-3 py-2.5 align-top num whitespace-nowrap">
                    <span className="mono text-md font-semibold">{fmt.conf(a.confidence)}</span>
                    <span className="mono text-2xs text-ink-soft ml-1">{fmt.range(a.confidence, a.interval)}</span>
                  </td>

                  <td className="px-3 py-2.5 align-top num">
                    <span className="mono text-sm text-network">{fmt.conf(a.novelty)}</span>
                  </td>

                  {/* Value moved, with the magnitude drawn. This is the one
                      quantity on the page with a real range, and length is the
                      channel the eye compares fastest. */}
                  <td className="px-3 py-2.5 align-top">
                    <div className="mono text-md font-semibold text-chain num">
                      {fmt.btc(a.total_out)}
                    </div>
                    {/* Right-anchored, so the bar ends where its number ends and
                        grows leftward. Left-anchored under a right-aligned figure,
                        the two read as unrelated objects. */}
                    <div className="flex justify-end mt-1.5"
                         title={`received ${fmt.btc(a.total_in)}`}>
                      <div className="h-1.5 anim-bar"
                           style={{ width: `${Math.max(3, mag * 100)}%`,
                                    background: 'var(--chain)',
                                    animationDelay: `${Math.min(ri, 14) * 18 + 90}ms` }} />
                    </div>
                  </td>

                  {/* Triage in place. Clicking the active verdict clears it. */}
                  <td className="px-3 py-2.5 align-top"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}>
                    <div className="flex gap-1">
                      {([['confirmed', 'confirm', 'confirm'], ['dismissed', 'dismiss', 'danger']] as const)
                        .map(([v, label, layer]) => {
                          const on = a.verdict === v;
                          return (
                            <button key={v} aria-pressed={on}
                                    title={on ? `${a.verdict_reason || 'no reason given'} · click to clear` : undefined}
                                    onClick={() => (on ? onVerdict(a.entity, '', '')
                                                       : setPending({ entity: a.entity, verdict: v }))}
                                    className="text-2xs px-2 h-6 border transition-colors duration-150
                                               cursor-pointer hover:border-ink"
                                    style={on
                                      ? { color: layerColor(layer), borderColor: layerColor(layer), background: layerWash(layer) }
                                      : { color: 'var(--ink-soft)', borderColor: 'var(--rule)', background: 'var(--surface)' }}>
                              {on ? (v === 'confirmed' ? 'confirmed' : 'dismissed') : label}
                            </button>
                          );
                        })}
                    </div>
                  </td>

                  <td className="pl-1 pr-3 py-2.5 align-top text-ink-dim">{ChevronRight}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      </>
  );
}
