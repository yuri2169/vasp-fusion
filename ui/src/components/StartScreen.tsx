/** The landing screen: the instrument at rest, waiting for a capture.
 *
 * Deliberately not a centred hero over a gradient. This is an asymmetric plate -
 * the argument and the controls on the left, a live diffusion field on the
 * right - because that is what the submitted wireframes look like and because a
 * forensics tool should read as apparatus rather than as a product page.
 *
 * The right-hand animation is the product's own thesis, not ornament: see
 * Propagation.tsx.
 */
import { useCallback, useRef, useState } from 'react';
import { api, fmt } from '../api';
import { Propagation } from './Propagation';
import { HowItWorks } from './HowItWorks';

const ACCEPT = ['.csv', '.json', '.jsonl', '.xml'];
const FIELDS = ['timestamp', 'src_ip', 'dst_ip', 'src_port', 'dst_port', 'txid',
  'input_addresses', 'output_addresses', 'input_amounts', 'output_amounts',
  'fee', 'script_type', 'geo_country', 'asn'];

export function StartScreen({ onStarted, lastRun, onViewLast }: {
  onStarted: (jobId: string, file: string) => void;
  lastRun: { rows: number; file: string } | null;
  onViewLast: () => void;
}) {
  const [over, setOver] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const send = useCallback(async (f: File) => {
    // Checked before the bytes move. A 240 MB upload that fails on extension at
    // the far end is a minute of the analyst's life for a one-line mistake.
    const ext = '.' + (f.name.split('.').pop() || '').toLowerCase();
    if (!ACCEPT.includes(ext)) {
      setErr(`${f.name} is not a capture this system reads. Accepted: ${ACCEPT.join(', ')}.`);
      return;
    }
    setErr(null); setBusy(f.name);
    try {
      const { job_id } = await api.upload(f);
      onStarted(job_id, f.name);
    } catch (e) { setBusy(null); setErr(String(e)); }
  }, [onStarted]);

  const runSample = useCallback(async (path?: string, label = 'bundled sample') => {
    setErr(null); setBusy(label);
    try {
      // Server-side: capture.csv is 241 MB and bulk.csv is 1 GB. Pushing those
      // through a browser file input to reach a server that already has them on
      // disk would be theatre with a failure mode.
      const { job_id } = await api.startRun(path);
      onStarted(job_id, label);
    } catch (e) { setBusy(null); setErr(String(e)); }
  }, [onStarted]);

  return (
    <div className="flex-1 flex flex-col">
    {/* The hero is one viewport tall and no more. It used to be the whole
        screen with its own inner scroller; now the PAGE scrolls, because there
        is an explainer under it and because the header's scrolled-ground state
        keys off window.scrollY - an inner scroller leaves the bar transparent
        over moving text. 5rem is the chrome above plus the status bar below. */}
    {/* The field is the ground for the whole landing, hero and explainer both -
        one canvas, fixed to the viewport, not a second instance. It is the
        product's own problem drawn live (see Propagation.tsx) and the pointer is
        a listening vantage point, so it stays playable the entire way down the
        page rather than only above the fold. Its pointer handler is on `window`
        and maps through the canvas rect, so `fixed` costs it nothing. */}
    <Propagation className="fixed inset-0 w-full h-full -z-10" />

    {/* No overflow-hidden. It was here to clip the field when the canvas lived
        inside this section; the canvas is now fixed to the viewport, and the
        clip is what stopped the veil from reaching up over the header. */}
    <section className="relative flex flex-col min-h-[calc(100svh-5rem)]">

      {/* A veil, not a frosted card. Solid ground under the column that holds
          the text, thinning to nothing across the field, so contrast is carried
          by the page rather than by a panel floating on top of it.

          -top-12 IS THE BUG FIX. The field is fixed to the viewport and runs
          from y=0, but this section starts below the 48px header, so the veil
          did too: the field was raw across the header band and veiled from the
          heading down, which drew a hard horizontal seam straight across the
          page at exactly the header's bottom edge. The veil now starts where the
          field does. The header is z-30 and still paints above it. */}
      <div aria-hidden className="absolute -top-12 left-0 right-0 bottom-0 pointer-events-none"
           style={{ background:
             'linear-gradient(to right, var(--paper) 0%, var(--paper) 26%,' +
             ' color-mix(in srgb, var(--paper) 80%, transparent) 46%,' +
             ' color-mix(in srgb, var(--paper) 28%, transparent) 70%, transparent 100%)' }} />
      <div aria-hidden className="absolute inset-x-0 bottom-0 h-32 pointer-events-none"
           style={{ background:
             'linear-gradient(to top, var(--paper) 0%,' +
             ' color-mix(in srgb, var(--paper) 55%, transparent) 55%, transparent 100%)' }} />

      <div className="relative flex-1 flex flex-col px-6 sm:px-12 lg:px-12 pt-12 sm:pt-12 pb-12
                      max-w-[46rem] pointer-events-none">
        <div className="pointer-events-auto">
          <h1 className="display text-ink anim-rise"
              style={{ fontSize: 'clamp(32px,5vw,60px)' }}>
            Network <span className="text-chain">⇄</span> chain<br />attribution
          </h1>

          <p className="text-md text-ink-soft mt-4 max-w-[52ch] anim-rise"
             style={{ animationDelay: '80ms' }}>
            Every blockchain tool can tell you that money moved suspiciously. This one
            correlates the <span className="text-network font-semibold">network layer</span> —
            IP, port, timing — with the <span className="text-chain font-semibold">chain
            layer</span> to say <em>who moved it</em>, and refuses to guess when the evidence
            is shared infrastructure.
          </p>
        {/* ------------------------------------------------------ dropzone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false);
                           const f = e.dataTransfer.files?.[0]; if (f) send(f); }}
          onClick={() => fileRef.current?.click()}
          role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') fileRef.current?.click(); }}
          aria-label="Drop a capture file here, or click to choose one"
          className={`relative mt-6 border cursor-pointer transition-colors duration-150 anim-rise
                      ${over ? 'border-chain bg-chain-wash' : 'border-rule bg-surface hover:border-ink'}`}
          style={{ animationDelay: '160ms' }}
        >
          {/* Registration marks, not a dashed rounded rectangle with a cloud. */}
          {(['tl', 'tr', 'bl', 'br'] as const).map((c) => (
            <span key={c} aria-hidden
                  className="absolute w-2.5 h-2.5 border-ink"
                  style={{
                    top: c[0] === 't' ? -1 : undefined, bottom: c[0] === 'b' ? -1 : undefined,
                    left: c[1] === 'l' ? -1 : undefined, right: c[1] === 'r' ? -1 : undefined,
                    borderTopWidth: c[0] === 't' ? 2 : 0, borderBottomWidth: c[0] === 'b' ? 2 : 0,
                    borderLeftWidth: c[1] === 'l' ? 2 : 0, borderRightWidth: c[1] === 'r' ? 2 : 0,
                    borderStyle: 'solid',
                    color: over ? 'var(--chain)' : 'var(--ink)',
                  }} />
          ))}

          <div className="px-6 py-8 text-center">
            {busy ? (
              <div className="figure text-chain" style={{ fontSize: 26 }}>{busy}</div>
            ) : (
              <>
                <div className="font-cond font-extrabold uppercase tracking-tight text-ink"
                     style={{ fontSize: 22 }}>
                  {over ? 'release to ingest' : 'drop a capture'}
                </div>
                <div className="text-sm text-ink-soft mt-1">
                  or click to choose · CSV, JSONL, XML
                </div>
              </>
            )}
          </div>
          <input ref={fileRef} type="file" accept={ACCEPT.join(',')} className="hidden"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); }} />
        </div>

        {err && (
          <p className="text-sm text-danger mt-3 anim-rise" role="alert">{err}</p>
        )}

        {/* -------------------------------------------------- sample runs */}
        <div className="mt-6 anim-rise" style={{ animationDelay: '240ms' }}>
          <div className="colhead mb-2">or score a bundled capture — no upload</div>
          <div className="flex flex-wrap gap-2">
            {[
              { name: 'capture.csv', label: 'demo', note: '565k rows · ~15 s' },
              { name: 'bulk.csv', label: 'bulk', note: '2.47M rows · ~40 s' },
            ].map((s) => (
              <button key={s.name} disabled={!!busy}
                      onClick={() => runSample(`data/samples/${s.name}`, s.name)}
                      className="text-left border border-rule bg-surface px-3 py-2 cursor-pointer
                                 transition-colors duration-150 hover:border-ink
                                 disabled:opacity-40 disabled:cursor-default">
                <div className="font-cond font-bold uppercase text-ink text-sm tracking-tight">
                  {s.label}
                </div>
                <div className="text-2xs text-ink-dim mono">{s.note}</div>
              </button>
            ))}
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-2xs text-ink-dim
                        anim-rise" style={{ animationDelay: '320ms' }}>
          <span className="flex items-center gap-2">
            <span aria-hidden className="w-1.5 h-1.5 inline-block bg-confirm" />
            runs entirely offline — no API, no cloud model
          </span>
          <span title={FIELDS.join(', ')} className="cursor-help">
            expects <span className="mono text-ink-soft">{FIELDS.length}</span> fields ·
            hover to list
          </span>
          {lastRun && (
            <button onClick={onViewLast}
                    className="text-chain hover:underline cursor-pointer">
              view last run instead ({fmt.int(lastRun.rows)} rows)
            </button>
          )}
        </div>
        </div>
      </div>

      {/* Says there is more, and nothing else. No chevron, no rule. */}
      <a href="#how"
         className="absolute left-1/2 -translate-x-1/2 bottom-11 z-10 colhead cursor-pointer
                    hover:text-ink transition-colors duration-150 anim-rise"
         style={{ animationDelay: '520ms' }}>
        how it works ↓
      </a>
    </section>

    <HowItWorks />
    </div>
  );
}
