/** Watchlist — follow the money from wallets the analyst already knows are bad.
 *
 * A seizure list or a sanctions list goes in; every actor within a few payment
 * hops of it comes out, with the path. Kept apart from the model on purpose:
 * being near a listed wallet is a reason to look, not evidence the model found
 * anything, so it never touches a score. Spread stops at exchange-like hubs,
 * or every customer of an exchange would inherit the taint.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, fmt, watchlistPhrase, type WatchlistHit, type WatchlistHits } from '../api';
import { Button, Chip, Eyebrow, IconUpload, Notice, Panel, Spinner, Tag } from '../ui';

const SHOWN = 200;
const DIRECTION: Record<WatchlistHit['direction'], string> = {
  seed: 'listed wallet', downstream: 'money from seed', upstream: 'money to seed',
};

export function WatchlistView({ onOpen }: { onOpen: (entity: string) => void }) {
  const [hits, setHits] = useState<WatchlistHits | null>(null);
  const [hops, setHops] = useState(3);
  const [queueOnly, setQueueOnly] = useState(false);
  const [label, setLabel] = useState('');
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api.watchlistHits(hops).then((h) => { setHits(h); setErr(null); })
      .catch((e) => setErr(String(e)));
  }, [hops]);
  useEffect(load, [load]);

  async function upload() {
    const f = fileRef.current?.files?.[0];
    if (!f) { setMsg('Choose a .csv or .txt file of addresses first.'); return; }
    setBusy(true);
    try {
      const r = await api.uploadWatchlist(f, label || 'watchlist');
      setMsg(`added ${fmt.int(r.added)} · rejected ${fmt.int(r.rejected)}`);
      if (fileRef.current) fileRef.current.value = '';
      load();
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }

  async function clear() {
    setBusy(true);
    try { await api.clearWatchlist(); setMsg('watchlist cleared'); load(); }
    catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }

  if (err) return <div className="p-4"><Notice title="Could not load the watchlist" layer="danger">{err}</Notice></div>;
  if (!hits) return <div className="p-8"><Spinner label="following the money…" /></div>;

  // Listed wallets first, then what is already in the queue, then by distance.
  const rows = [...hits.hits]
    .filter((h) => !queueOnly || h.in_queue)
    .sort((x, y) => Number(y.hops === 0) - Number(x.hops === 0)
      || Number(y.in_queue) - Number(x.in_queue) || x.hops - y.hops);
  const inQueue = hits.hits.filter((h) => h.in_queue).length;
  const found = hits.seeds.filter((s) => s.entity).length;

  return (
    <div className="p-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3">
        <h1 className="display text-ink">watchlist</h1>
        <span className="text-sm text-ink-soft">
          Distance on the payment graph from wallets you supplied. It is not the model's
          score and it does not mean guilt.
        </span>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,2.4fr)] gap-3">
        {/* ---------- left: what went in ---------- */}
        <div className="space-y-3 min-w-0">
          <Panel>
            <Eyebrow layer="danger">add known-bad wallets</Eyebrow>
            <div className="flex flex-col gap-2">
              <input ref={fileRef} type="file" accept=".csv,.txt"
                     aria-label="Watchlist file"
                     className="text-sm file:mr-3 file:h-8 file:px-3 file:border file:border-rule
                                file:bg-surface file:text-ink-soft file:mono file:text-sm
                                file:cursor-pointer" />
              <input value={label} onChange={(e) => setLabel(e.target.value)}
                     placeholder="Label, e.g. seizure list 2026-09"
                     aria-label="Watchlist label" maxLength={80}
                     className="h-8 bg-surface border border-rule px-2 text-sm
                                placeholder:text-ink-dim focus:border-ink outline-none" />
              <div className="flex items-center gap-2">
                <Button variant="default" onClick={upload} disabled={busy}>
                  <IconUpload /> upload
                </Button>
                <Button variant="ghost" onClick={clear} disabled={busy || hits.seeds.length === 0}>
                  clear watchlist
                </Button>
              </div>
              {msg && <span className="mono text-2xs text-ink-soft">{msg}</span>}
              <span className="text-2xs text-ink-dim">
                One address per line, optionally followed by a comma and a label.
              </span>
            </div>
          </Panel>

          <Panel pad={false}>
            <div className="px-4 pt-3">
              <Eyebrow right={`${found} of ${hits.seeds.length} in this capture`}>listed wallets</Eyebrow>
            </div>
            {hits.seeds.length === 0 ? (
              <p className="px-4 pb-4 text-sm text-ink-soft">No wallets listed yet.</p>
            ) : (
              <div className="max-h-[28rem] overflow-y-auto">
                <table className="w-full">
                  <tbody>
                    {[...hits.seeds].sort((x, y) => Number(!!y.entity) - Number(!!x.entity)).map((s) => (
                      <tr key={s.address} className="border-t border-rule-soft">
                        <td className="px-4 py-1.5 mono text-2xs break-all">{s.address}</td>
                        <td className="px-4 py-1.5 text-2xs whitespace-nowrap">
                          {s.entity
                            ? <span className="mono text-chain">→ {s.entity}</span>
                            : <span className="text-ink-dim">not in this capture</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>

        {/* ---------- right: what it reaches ---------- */}
        <Panel pad={false}>
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-rule-soft bg-surface-2">
            <span className="text-sm text-ink-soft">
              <span className="mono font-semibold text-ink">{fmt.int(hits.n_reached ?? hits.hits.length)}</span> actors
              within {hops} hop{hops > 1 ? 's' : ''} ·{' '}
              <span className="mono font-semibold text-fusion">{fmt.int(inQueue)}</span> already in the queue
            </span>
            <span className="ml-auto flex items-center gap-1">
              <span className="colhead mr-1">hops</span>
              {[1, 2, 3].map((h) => (
                <Chip key={h} active={hops === h} onClick={() => setHops(h)}>{h}</Chip>
              ))}
              <span className="w-px h-5 bg-rule mx-1" />
              <Chip layer="fusion" active={queueOnly} onClick={() => setQueueOnly(!queueOnly)}>
                in queue only
              </Chip>
            </span>
          </div>

          {!hits.available ? (
            <div className="p-4"><Notice title="Re-score this capture">{hits.note}</Notice></div>
          ) : hits.seeds.length === 0 ? (
            <p className="p-6 text-sm text-ink-soft">
              Upload a list of addresses to see which actors in this capture sit near them.
            </p>
          ) : rows.length === 0 ? (
            <p className="p-6 text-sm text-ink-soft">
              {found === 0 ? 'None of these wallets are in this capture. Upload a list made for it.'
                           : 'Nothing matches this filter.'}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse min-w-[52rem]">
                <thead>
                  <tr className="border-b border-rule">
                    {['actor', 'hops', 'direction', 'path to the listed wallet', 'status'].map((h, i) => (
                      <th key={h} className={`colhead px-3 py-2 ${i === 1 ? 'text-right' : 'text-left'}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, SHOWN).map((h) => (
                    <tr key={h.entity} className="border-b border-rule-soft align-top">
                      <td className="px-3 py-2 mono text-sm whitespace-nowrap">
                        {h.in_queue ? (
                          <button onClick={() => onOpen(h.entity)} title={watchlistPhrase(h)}
                                  className="text-chain font-semibold hover:underline cursor-pointer">
                            {h.entity}
                          </button>
                        ) : <span title={watchlistPhrase(h)}>{h.entity}</span>}
                      </td>
                      <td className="px-3 py-2 num mono text-sm">{h.hops}</td>
                      <td className="px-3 py-2 text-sm text-ink-soft whitespace-nowrap">
                        {DIRECTION[h.direction]}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-1">
                          {h.path.map((p, i) => (
                            <span key={p} className="flex items-center gap-1">
                              {i > 0 && <span aria-hidden className="text-ink-dim text-2xs">→</span>}
                              <span className={`mono text-2xs px-1.5 py-0.5 ${i === h.path.length - 1
                                ? 'text-danger bg-danger-wash' : 'text-ink-soft bg-surface-3'}`}>{p}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        {h.in_queue
                          ? <Tag layer="fusion">in queue · rank {h.rank}</Tag>
                          : <span className="text-sm text-ink-dim">not in queue</span>}
                        {h.is_hub && (
                          <span className="block text-2xs text-ink-dim mt-1">
                            exchange-like hub, not spread through
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > SHOWN && (
                <p className="px-4 py-2 text-2xs text-ink-dim">
                  showing the nearest {SHOWN} of {fmt.int(rows.length)}
                  {(hits.n_reached ?? 0) > hits.hits.length
                    ? ` (of ${fmt.int(hits.n_reached ?? 0)} reached, the server returns the nearest plus every queued lead)`
                    : ''}
                </p>
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
