/** Plate 04 — the alert queue.
 *
 * The ingest receipt sits above everything, always open, so the analyst knows
 * what was and was not parsed before trusting a row. The footer states how many
 * entities the threshold hides.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { api, fmt, nearWatchlist, type Alert, type Receipt, type TxRow, type WatchlistHit } from '../api';
import { DossierView, FocusView, TableView } from './QueueViews';
import { Bar, Button, Chip, Counter, IconFilter, Notice, Panel, Spinner, Stat, Tag } from '../ui';

const TYPOLOGIES = ['peel_chain', 'fan_out_in', 'rapid_layering',
  'mixer_passthrough', 'dormancy_burst', 'cross_asn_structuring'];

/** Drawn marks. One stroke weight, one grid - no glyphs standing in for icons. */
const mark = (d: ReactNode, w = 14) => (
  <svg viewBox="0 0 14 14" width={w} height={w} fill="none" stroke="currentColor"
       strokeWidth="1.5" strokeLinecap="square" aria-hidden>{d}</svg>
);
const ArrowRight = mark(<><path d="M2 7h9" /><path d="M8 4l3 3-3 3" /></>);
const IcoSearch = mark(<><circle cx="6" cy="6" r="4" /><path d="M9 9l3.5 3.5" /></>, 15);

type SortKey = 'rank' | 'confidence' | 'novelty' | 'total_out' | 'n_ips';

/** The reduction - rows to actors to leads - with the ingest receipt always
 *  open beneath it: what was read, rejected and how long each stage took. */
function Funnel({ r, leads }: { r: Receipt; leads: number }) {
  const q = r.rows_quarantined ?? 0;

  const step = (value: ReactNode, label: string, layer?: string) => (
    <div className="flex flex-col gap-0.5">
      <span className="figure" style={layer ? { color: `var(${layer})` } : undefined}>{value}</span>
      <span className="colhead">{label}</span>
    </div>
  );

  return (
    <Panel pad={false} className="mb-4">
      <div className="flex flex-wrap items-end gap-x-5 gap-y-3 px-4 pt-3 pb-3">
        {step(<Counter value={r.rows_read} format={(n) => fmt.int(Math.round(n))} />,
              `${r.format.toUpperCase()} rows ingested`)}
        <span className="hidden sm:inline text-rule mb-2.5">{ArrowRight}</span>
        {step(fmt.int(r.n_entities_resolved), 'actors resolved', '--chain')}
        <span className="hidden sm:inline text-rule mb-2.5">{ArrowRight}</span>
        {step(fmt.int(leads), 'ranked leads', '--fusion')}

        <div className="ml-auto flex items-center gap-2 mb-1">
          {q > 0 && <Tag layer="danger">{fmt.int(q)} quarantined</Tag>}
          {r.chain_only_mode
            ? <Tag layer="danger" title="No usable src_ip column in this capture">chain-only mode</Tag>
            : <Tag layer="network">network layer active</Tag>}
          {r.degraded_no_model
            ? <Tag layer="danger" title="No trained artefacts — unsupervised only">no model</Tag>
            : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-rule-soft
                      bg-surface-2 px-4 py-2">
        <span className="text-2xs text-ink-dim">
          <span className="mono text-ink">{r.file}</span> · scored in{' '}
          <span className="mono text-confirm font-semibold">
            <Counter value={r.duration_s} decimals={2} duration={900} />s
          </span>
          {' '}· <span className="mono">{fmt.int(r.rows_per_second)}</span> rows/s
        </span>
      </div>

      <div className="border-t border-rule-soft px-4 py-3">
        <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
          <Stat label="quarantined" value={fmt.int(q)} layer={q > 0 ? 'danger' : undefined}
                sub={q > 0 ? Object.keys(r.quarantine_breakdown).join(', ') : 'no rows rejected'} />
          <Stat label="duplicates" value={fmt.int(r.duplicates_removed)}
                sub="same txid·src·dst·ts" />
          <Stat label="with activity" value={fmt.int(r.n_entities_active)}
                sub="the analysis set" />
          <Stat label="transactions" value={fmt.int(r.n_transactions)}
                sub={`${fmt.int(r.n_graph_edges)} graph edges`} />
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 pt-2 border-t border-rule-soft">
          <span className="colhead">stage timings</span>
          {(() => {
            const t = Object.entries(r.timings || {});
            const slowest = t.reduce((a, b) => (b[1] > a[1] ? b : a), t[0] || ['', 0])[0];
            return t.map(([k, v]) => (
              <span key={k} className={`text-2xs ${k === slowest ? 'text-ink' : 'text-ink-soft'}`}>
                {k}{' '}
                <span className={`mono font-semibold ${k === slowest ? 'text-fusion' : 'text-ink'}`}>
                  {v}s
                </span>
              </span>
            ));
          })()}
        </div>
      </div>
    </Panel>
  );
}

export function AlertQueue({ onOpen, country, onClearCountry }: {
  onOpen: (entity: string) => void;
  country?: string; onClearCountry?: () => void;     // set when arriving from the map
}) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(0.55);
  const [typology, setTypology] = useState<string>('');
  const [asnType, setAsnType] = useState<string>('');
  const [unreviewed, setUnreviewed] = useState(false);
  const [nearOnly, setNearOnly] = useState(false);
  // Distance to an analyst-supplied watchlist. Shown beside the model's call,
  // never folded into it.
  const [near, setNear] = useState<Map<string, WatchlistHit>>(new Map());
  const [showSuppressed, setShowSuppressed] = useState(false);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'rank', dir: 'asc' });
  // null until the user actually navigates. Starting at 0 painted row one as
  // selected the moment the page loaded, which claims a choice nobody made and
  // draws the eye to rank 1 as if it were special beyond simply being first.
  // Three presentations of the same queue, switchable against real data.
  // Persisted so flipping between them survives a reload while they are judged.
  const [view, setView] = useState<'table' | 'dossier' | 'focus'>(() => {
    try { return (localStorage.getItem('btcfusion.queueview') as never) || 'table'; }
    catch { return 'table'; }
  });
  useEffect(() => {
    try { localStorage.setItem('btcfusion.queueview', view); } catch { /* private mode */ }
  }, [view]);
  const [focusIdx, setFocusIdx] = useState(0);
  // Triage without leaving the screen. Optimistic locally so the row responds at
  // once; the run's own re-rank picks it up next time the capture is scored.
  const setVerdict = (entity: string, verdict: string, reason = '') => {
    setAlerts((prev) => prev.map((a) => (a.entity === entity
      ? { ...a, verdict, verdict_reason: reason } : a)));
    api.verdict(entity, verdict, reason).catch(() => {
      setAlerts((prev) => prev.map((a) => (a.entity === entity ? { ...a, verdict: '' } : a)));
    });
  };
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const searchRef = useRef<HTMLInputElement>(null);
  // The PS asks why a wallet OR a transaction was flagged. Entities are the
  // investigative unit and stay the default; transactions are one click away.
  const [level, setLevel] = useState<'entities' | 'transactions'>('entities');
  const [txRows, setTxRows] = useState<TxRow[]>([]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([api.latestRun(), api.alerts({ min_confidence: 0 })])
      .then(([runRes, alertRes]) => {
        if (!live) return;
        setReceipt(runRes.run?.receipt ?? null);
        setAlerts(alertRes.alerts);
        if (runRes.run?.receipt?.threshold) setThreshold(runRes.run.receipt.threshold);
        setErr(null);
      })
      .catch((e) => live && setErr(String(e)))
      .finally(() => live && setLoading(false));
    api.watchlistHits().then((h) => live && setNear(nearWatchlist(h))).catch(() => {});
    return () => { live = false; };
  }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = alerts.filter((a) =>
      (showSuppressed || a.confidence >= threshold)
      && (!typology || a.typologies.includes(typology))
      && (!asnType || a.top_asn_type === asnType)
      && (!unreviewed || !a.verdict)
      && (!nearOnly || near.has(a.entity))
      && (!country || a.top_country === country)
      && (!q || a.entity.toLowerCase().includes(q))
    );
    const dir = sort.dir === 'asc' ? 1 : -1;
    return [...rows].sort((x, y) => {
      const vx = sort.key === 'total_out' ? x.total_out
        : sort.key === 'n_ips' ? x.n_ips
        : sort.key === 'novelty' ? x.novelty
        : sort.key === 'confidence' ? x.confidence : x.rank;
      const vy = sort.key === 'total_out' ? y.total_out
        : sort.key === 'n_ips' ? y.n_ips
        : sort.key === 'novelty' ? y.novelty
        : sort.key === 'confidence' ? y.confidence : y.rank;
      return (vx - vy) * dir;
    });
  }, [alerts, threshold, typology, asnType, unreviewed, nearOnly, near, country, showSuppressed, query, sort]);

  // `/` focuses search, Escape clears it. Analysts in this genre live on the
  // keyboard; the queue previously had no shortcut of any kind.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === 'Escape') {
        if (document.activeElement === searchRef.current) {
          setQuery('');
          searchRef.current?.blur();
        }
      } else if ((e.key === 'j' || e.key === 'k' || e.key === 'ArrowDown'
                  || e.key === 'ArrowUp' || e.key === 'ArrowRight'
                  || e.key === 'ArrowLeft') && tag !== 'INPUT') {
        e.preventDefault();
        const fwd = ['j', 'ArrowDown', 'ArrowRight'].includes(e.key);
        setFocusIdx((i) => {
          const n = visibleRef.current.length;
          if (!n) return 0;
          return Math.min(n - 1, Math.max(0, i + (fwd ? 1 : -1)));
        });
      } else if (e.key === 'Enter' && tag !== 'INPUT' && tag !== 'BUTTON') {
        const a = visibleRef.current[focusRef.current];
        if (a) { e.preventDefault(); onOpenRef.current(a.entity); }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Refs, because the key handler is bound once and must not close over a
  // stale filtered list.
  const visibleRef = useRef<Alert[]>([]);
  const focusRef = useRef(0);
  visibleRef.current = visible;
  focusRef.current = focusIdx;


  useEffect(() => {
    if (level !== 'transactions') return;
    api.transactions(0, 200).then((r) => setTxRows(r.transactions)).catch(() => {});
  }, [level]);

  const suppressed = alerts.filter((a) => a.confidence < threshold).length;
  // Scale the magnitude bars to the whole queue, not to what is currently
  // filtered: a bar that rescales as you type is not a comparison.
  const maxValue = useMemo(
    () => Math.max(1, ...alerts.map((a) => a.total_out || 0)), [alerts]);
  const asnTypes = useMemo(
    () => Array.from(new Set(alerts.map((a) => a.top_asn_type).filter(Boolean))), [alerts]);

  if (loading) return <div className="p-8"><Spinner label="loading alert queue…" /></div>;
  if (err) return <div className="p-4"><Notice title="Could not load alerts" layer="danger">{err}</Notice></div>;
  if (!receipt) return (
    <div className="p-4">
      <Notice title="No run yet">
        Load a capture to score it. Use <span className="mono">Load capture</span> above, or run{' '}
        <span className="mono">make run</span> from the repository root.
      </Notice>
    </div>
  );

  return (
    <div className="p-3">
      <Funnel r={receipt} leads={alerts.length} />

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <div className="flex items-center gap-0.5" role="tablist" aria-label="Alert granularity">
          {(['entities', 'transactions'] as const).map((l) => (
            <button key={l} role="tab" aria-selected={level === l}
                    onClick={() => setLevel(l)}
                    className="mono text-sm px-3 h-9 border transition-colors duration-150 cursor-pointer"
                    style={level === l
                      ? { borderColor: 'var(--ink)', background: 'var(--ink)', color: 'var(--paper)' }
                      : { borderColor: 'var(--rule)', color: 'var(--ink-soft)', background: 'var(--surface)' }}>
              {l}
            </button>
          ))}
        </div>
        <label className="ml-auto relative flex items-center">
          <span className="absolute left-3 text-ink-soft pointer-events-none">{IcoSearch}</span>
          <input
            ref={searchRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search entity ID"
            aria-label="Search by entity ID"
            className="h-9 w-80 bg-surface border border-ink-soft pl-9 pr-16 mono text-md text-ink
                       placeholder:text-ink-dim placeholder:font-sans focus:border-ink
                       focus:outline focus:outline-1 focus:outline-ink outline-none"
          />
          {query ? (
            <button onClick={() => { setQuery(''); searchRef.current?.focus(); }}
                    className="absolute right-2 h-6 px-2 text-2xs text-ink-soft hover:text-ink cursor-pointer">
              clear
            </button>
          ) : null}
        </label>
      </div>

      {level === 'transactions' ? (
        <Panel pad={false}>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse min-w-[56rem]">
              <thead>
                <tr className="border-b border-rule">
                  {['txid', 'entity', 'time', 'value', 'in/out', 'entropy', 'score'].map((h, i) => (
                    <th key={h} className={`eyebrow px-3 py-2 ${i >= 3 ? 'text-right' : 'text-left'}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {txRows.map((t) => (
                  <tr key={t.txid} className="row-hover border-b border-rule-soft cursor-pointer">
                    <td className="px-3 py-2 mono text-sm">{t.txid.slice(0, 22)}…</td>
                    <td className="px-3 py-2 mono text-sm">
                      <button onClick={() => onOpen(t.entity)}
                              className="text-chain hover:underline cursor-pointer">{t.entity}</button>
                    </td>
                    <td className="px-3 py-2 mono text-2xs text-ink-dim">{fmt.time(String(t.ts))}</td>
                    <td className="px-3 py-2 num mono text-sm">₿ {fmt.btc(t.value_out)}</td>
                    <td className="px-3 py-2 num mono text-2xs">{t.n_inputs}/{t.n_outputs}</td>
                    <td className="px-3 py-2 num mono text-2xs">{(t.output_entropy ?? 0).toFixed(2)}</td>
                    <td className="px-3 py-2 num">
                      <div className="flex items-center gap-2 justify-end">
                        <Bar value={t.tx_score} width={70} height={8} />
                        <span className="mono text-md font-semibold">{fmt.conf(t.tx_score)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {txRows.length === 0 && (
            <div className="p-6 text-center text-sm text-ink-soft">
              No transaction-level scores in this run.
            </div>
          )}
        </Panel>
      ) : (<>
      {/* --- filters ------------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="colhead flex items-center gap-2"><IconFilter className="w-3 h-3" />filters</span>
        <Chip active={!typology} onClick={() => setTypology('')}>
          all typologies <span className="opacity-60">{alerts.length}</span>
        </Chip>
        {/* A filter that matches nothing is not a filter, it is a disabled button
            taking up a slot. Thirteen chips wrapped onto two rows here; dropping
            the empty ones leaves only facets that can actually change the view. */}
        {TYPOLOGIES.map((t) => {
          const n = alerts.filter((a) => a.typologies.includes(t)).length;
          if (n === 0) return null;
          return (
            <Chip key={t} active={typology === t}
                  onClick={() => setTypology(typology === t ? '' : t)}>
              {fmt.typology(t)} <span className="opacity-60">{n}</span>
            </Chip>
          );
        })}
        {/* Host class is a second facet, and five more chips for it pushed the
            filter row onto two lines at every width. A native select holds the
            same five choices in one control, sorts itself, and needs no code. */}
        {country && (
          <Chip layer="network" active onClick={onClearCountry}>
            {fmt.country(country)} <span className="mono opacity-60">{country}</span>
            <span aria-label="clear the country filter" className="ml-1">×</span>
          </Chip>
        )}
        {near.size > 0 && (
          <Chip layer="danger" active={nearOnly} onClick={() => setNearOnly(!nearOnly)}>
            near watchlist{' '}
            <span className="opacity-60">{alerts.filter((a) => near.has(a.entity)).length}</span>
          </Chip>
        )}
        {asnTypes.length > 0 && (
          <>
            <span className="w-px h-5 bg-rule mx-1" />
            <label className="colhead" htmlFor="asn">host class</label>
            <select id="asn" value={asnType}
                    onChange={(e) => setAsnType(e.target.value)}
                    className="h-7 bg-surface border px-2 mono text-sm cursor-pointer
                               outline-none focus:border-ink"
                    style={{ borderColor: asnType ? 'var(--network)' : 'var(--rule)',
                             color: asnType ? 'var(--network)' : 'var(--ink-soft)' }}>
              <option value="">any</option>
              {asnTypes.map((t) => {
                const n = alerts.filter((a) => a.top_asn_type === t).length;
                return <option key={t} value={t}>{t} ({n})</option>;
              })}
            </select>
          </>
        )}

      </div>

      {/* --- rail + briefing ----------------------------------------------- */}
      {/* Two panes, not a table. Sixty leads scanned on the left, one lead read
          on the right. The spreadsheet gave every lead nineteen small values and
          no room for the one field that says why it is here; this gives the rail
          the four channels worth scanning and the briefing everything else. */}
      <Panel pad={false}>
        <div className="flex items-center gap-3 px-3 py-2 border-b border-rule-soft bg-surface-2">
          <label htmlFor="thr" className="colhead">confidence threshold</label>
          <input id="thr" type="range" min={0.05} max={0.95} step={0.05} value={threshold}
                 className="w-40 accent-[var(--fusion)]"
                 onChange={(e) => setThreshold(Number(e.target.value))} />
          <span className="mono text-md font-semibold w-9 text-fusion">{threshold.toFixed(2)}</span>
          <Chip layer="confirm" active={unreviewed} onClick={() => setUnreviewed(!unreviewed)}>
            unreviewed only
          </Chip>
          <label htmlFor="sort" className="colhead ml-2">order by</label>
          <select id="sort" value={`${sort.key}:${sort.dir}`}
                  onChange={(e) => {
                    const [key, dir] = e.target.value.split(':');
                    setSort({ key: key as SortKey, dir: dir as 'asc' | 'desc' });
                  }}
                  className="h-6 bg-surface border border-rule px-1 mono text-2xs
                             text-ink-soft cursor-pointer outline-none focus:border-ink">
            <option value="rank:asc">model rank</option>
            <option value="total_out:desc">value moved</option>
            <option value="novelty:desc">novelty</option>
            <option value="confidence:desc">confidence</option>
            <option value="n_ips:desc">announcing IPs</option>
          </select>
          <span className="flex items-center gap-0.5 ml-2">
            <span className="colhead mr-1">layout</span>
            {([['table', 'table'], ['dossier', 'dossier'], ['focus', 'focus']] as const)
              .map(([k, label]) => (
                <button key={k} onClick={() => setView(k)} aria-pressed={view === k}
                        className="mono text-2xs px-2 h-6 border transition-colors
                                   duration-150 cursor-pointer"
                        style={view === k
                          ? { borderColor: 'var(--ink)', background: 'var(--ink)', color: 'var(--paper)' }
                          : { borderColor: 'var(--rule)', color: 'var(--ink-soft)' }}>
                  {label}
                </button>
              ))}
          </span>
          <span className="flex items-center gap-3 ml-auto text-2xs text-ink-dim">
            <span className="hidden xl:flex items-center gap-2">
              <span className="colhead">evidence</span>
              {([['--chain', 'chain'], ['--network', 'network'], ['--fusion', 'model']] as const)
                .map(([v, l]) => (
                  <span key={l} className="flex items-center gap-1">
                    <span className="w-2 h-3 inline-block" style={{ background: `var(${v})` }} />
                    {l}
                  </span>
                ))}
            </span>
            <span aria-hidden className="hidden xl:inline text-rule">|</span>
            <span>
              <span className="mono text-ink">{visible.length}</span> shown ·{' '}
              <span className="mono">{suppressed}</span> below
            </span>
          </span>
        </div>

        <div>
          {view === 'table' && (
            <TableView rows={visible} maxValue={maxValue} threshold={threshold}
                       sort={sort} onOpen={onOpen} onVerdict={setVerdict} near={near}
                       onSort={(k) => setSort((s0) => ({
                         key: k as SortKey,
                         dir: s0.key === k && s0.dir === 'asc' ? 'desc' : 'asc',
                       }))} />
          )}
          {view === 'dossier' && (
            <DossierView rows={visible} maxValue={maxValue} onOpen={onOpen} near={near} />
          )}
          {view === 'focus' && (
            <FocusView rows={visible} index={Math.min(focusIdx, Math.max(0, visible.length - 1))}
                       onIndex={setFocusIdx} onOpen={onOpen} onVerdict={setVerdict} />
          )}
          {visible.length === 0 && (
            <div className="p-10 text-center text-sm text-ink-soft">
              No leads match these filters. Lower the threshold or clear a filter.
            </div>
          )}
        </div>
      </Panel>

      </>)}

      {suppressed > 0 && (
        <div className="flex items-center gap-4 mt-3 px-4 py-2 bg-surface-2">
          <span className="text-sm text-ink-soft">
            <span className="mono font-semibold text-ink">{fmt.int(suppressed)}</span>{' '}
            {suppressed === 1 ? 'entity' : 'entities'} below {threshold.toFixed(2)}{' '}
            {suppressed === 1 ? 'is' : 'are'} hidden.
          </span>
          <span className="ml-auto">
            <Button variant={showSuppressed ? 'default' : 'ghost'}
                    onClick={() => setShowSuppressed(!showSuppressed)}>
              {showSuppressed ? 'hide' : 'show'}
            </Button>
          </span>
        </div>
      )}
    </div>
  );
}
