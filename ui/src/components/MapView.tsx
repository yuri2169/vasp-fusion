/** Map — where the leads announce from, drawn entirely offline.
 *
 * The world is bundled (Natural Earth via world-atlas, 1:50m - the 1:110m file
 * drops Singapore, Seychelles and Hong Kong, three of the demo's lead countries).
 * Nothing is fetched but our own /api/geo.
 *
 * What each mark claims, and nothing more:
 *   shading   how many leads have their top-ranked announcing IP in that country
 *             (the candidate the attribution engine ranks first - by confidence,
 *             not by count), model output so --fusion, four steps fixed to the run
 *   dots      one per lead; hollow when that IP is a VPN or Tor exit, because
 *             then the country is the relay's, not the person's
 *   lines     two countries whose IPs both announced the same lead (--network,
 *             a network-layer fact); undirected, so the pulse runs both ways
 *
 * Motion follows docs/ui_architecture.md §7: a one-off scan lights the map
 * west to east, clusters ping softly, and the replay adds each lead at its first
 * transaction. Reduced motion shows the final state and none of the movement.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent as RKeyboardEvent, PointerEvent as RPointerEvent, ReactNode } from 'react';
import { geoArea, geoCentroid, geoGraticule10, geoNaturalEarth1, geoPath } from 'd3-geo';
import { feature, merge, mesh } from 'topojson-client';
import type {
  GeometryCollection, MultiPolygon as TopoMultiPolygon, Polygon as TopoPolygon, Topology,
} from 'topojson-specification';
import type { Feature, FeatureCollection, MultiPolygon, Polygon } from 'geojson';
import world from 'world-atlas/countries-50m.json';
import { api, fmt, type GeoData, type GeoLead } from '../api';
import { ISO_NUMERIC } from '../isoNumeric';
import { Chip, Counter, Eyebrow, Notice, Panel, Spinner } from '../ui';

/* ─────────────────────────── the world, prepared once ─────────────────────── */

type Shape = Feature<Polygon | MultiPolygon, { name: string }>;
const TOPO = world as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>;
const SHAPES = (feature(TOPO, TOPO.objects.countries) as unknown as
  FeatureCollection<Polygon | MultiPolygon, { name: string }>).features as Shape[];
const ANTARCTICA = '010';
// One dissolved landmass: its outline IS the coastline, so a single path both
// fills the land and draws the coast. Country borders are a separate mesh.
// merge() takes an ARRAY of geometries. Its type definition also admits a bare
// GeometryCollection, which throws at load - and took the whole app down once.
const LAND = merge(TOPO, TOPO.objects.countries.geometries.filter(
  (g): g is TopoPolygon<{ name: string }> | TopoMultiPolygon<{ name: string }> =>
    (g.type === 'Polygon' || g.type === 'MultiPolygon') && g.id !== ANTARCTICA));
const LAND_FC = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: LAND, properties: {} }] } as FeatureCollection;
const BORDERS = mesh(TOPO, TOPO.objects.countries, (a, b) => a !== b);
const GRATICULE = geoGraticule10();
const SPHERE = { type: 'Sphere' } as const;

const BY_NUMERIC = new Map<string, Shape[]>();
for (const s of SHAPES) {
  if (s.id == null) continue;
  const k = String(s.id);
  // Two shapes can share an id (036 is Australia AND Ashmore and Cartier Is.).
  BY_NUMERIC.set(k, [...(BY_NUMERIC.get(k) ?? []), s]);
}
// GeoIP databases tag Kosovo 'XK'; ISO never assigned it and the atlas gives it no id.
const BY_NAME: Record<string, string> = { XK: 'Kosovo' };

function shapesOf(code: string): Shape[] {
  if (BY_NAME[code]) return SHAPES.filter((s) => s.properties.name === BY_NAME[code]);
  const num = ISO_NUMERIC[code]?.[0];
  return num ? BY_NUMERIC.get(num) ?? [] : [];
}

/** Lon/lat of the country's largest landmass. The centroid of the whole shape
 *  would put France in the Atlantic (French Guiana) and the US near Canada. */
function anchorOf(shapes: Shape[]): [number, number] | null {
  let best: Polygon | null = null, bestArea = -1;
  for (const s of shapes) {
    const g = s.geometry;
    if (!g) continue;
    for (const coordinates of g.type === 'Polygon' ? [g.coordinates] : g.coordinates) {
      const p: Polygon = { type: 'Polygon', coordinates };
      const a = geoArea(p);
      if (a > 2 * Math.PI) continue;          // a ring wound the wrong way reads as the whole globe
      if (a > bestArea) { bestArea = a; best = p; }
    }
  }
  return best ? (geoCentroid(best) as [number, number]) : null;
}

/* ─────────────────────────────── the data ─────────────────────────────────── */

const EXIT = new Set(['vpn', 'tor']);
const HOSTING = new Set(['hosting', 'cdn']);
const OWN = new Set(['residential', 'mobile']);

type Mode = 'all' | 'own' | 'hosting' | 'exit';
const MODES: { key: Mode; label: string }[] = [
  { key: 'all', label: 'all leads' },
  { key: 'own', label: 'residential or mobile' },
  { key: 'hosting', label: 'hosting or CDN' },
  { key: 'exit', label: 'VPN or Tor exit' },
];

type Tally = { code: string; leads: number; exit: number; hosting: number; own: number; named: number };

/** Same rules as /api/geo, applied to whichever leads are on the map. */
function tally(leads: GeoLead[]): Map<string, Tally> {
  const m = new Map<string, Tally>();
  for (const l of leads) {
    if (!l.country) continue;
    const t = m.get(l.country) ?? { code: l.country, leads: 0, exit: 0, hosting: 0, own: 0, named: 0 };
    t.leads += 1;
    if (EXIT.has(l.asn_type)) t.exit += 1;
    if (HOSTING.has(l.asn_type)) t.hosting += 1;
    if (OWN.has(l.asn_type)) t.own += 1;
    if (l.status === 'ok') t.named += 1;
    m.set(l.country, t);
  }
  return m;
}

const valueOf = (t: Tally | undefined, mode: Mode) => !t ? 0
  : mode === 'all' ? t.leads : mode === 'exit' ? t.exit : mode === 'hosting' ? t.hosting : t.own;

type Link = { key: string; a: string; b: string; n: number };

/** Countries joined by a lead: its top-ranked country and each other country its
 *  candidate IPs sit in. One count per lead per pair. */
function linksOf(leads: GeoLead[]): Link[] {
  const m = new Map<string, Link>();
  for (const l of leads) {
    if (!l.country) continue;
    for (const c of l.countries) {
      if (c === l.country) continue;
      const [a, b] = l.country < c ? [l.country, c] : [c, l.country];
      const key = `${a}~${b}`;
      const k = m.get(key) ?? { key, a, b, n: 0 };
      k.n += 1;
      m.set(key, k);
    }
  }
  return [...m.values()].sort((x, y) => y.n - x.n || x.key.localeCompare(y.key));
}

/* Four steps of the model-output colour, mixed into the surface so they hold in
   both themes. The scale is fixed to the whole run: during a replay a country
   darkens because its count grew, never because the scale shrank. */
// Measured, both themes: lightest step 1.54x the unshaded land (light), each step
// >=1.36x the next. 24% had left a one-lead country at 1.23x - too faint to find.
const STEP_MIX = [38, 56, 74, 94];
const stepOf = (v: number, max: number) => (v <= 0 || max <= 0 ? -1 : Math.min(3, Math.ceil((4 * v) / max) - 1));
const stepFill = (k: number) => `color-mix(in srgb, var(--fusion) ${STEP_MIX[k]}%, var(--surface))`;
function stepRanges(max: number): { k: number; lo: number; hi: number }[] {
  return [0, 1, 2, 3].map((k) => ({ k, lo: Math.floor((k * max) / 4) + 1, hi: Math.floor(((k + 1) * max) / 4) }))
    .filter((r) => r.hi >= r.lo);
}

/* ─────────────────────────────── layout ───────────────────────────────────── */

// At 1000px of map a dot is 2.6px; narrower maps shrink it (to 60%) so a
// cluster never swamps its country. `u` carries that factor.
const DOT_R = 2.6;
const DOT_STEP = 3.7;                       // Vogel spiral spacing: neighbours never touch
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const unitFor = (width: number) => Math.min(1, Math.max(0.6, width / 1000));
const slot = (i: number, n: number, u: number): [number, number] => {
  if (n === 1) return [0, 0];
  const r = DOT_STEP * u * Math.sqrt(i + 0.5), a = i * GOLDEN;
  return [r * Math.cos(a), r * Math.sin(a)];
};
const clusterR = (n: number, u: number) =>
  (n <= 1 ? DOT_R : DOT_STEP * Math.sqrt(n - 0.5) + DOT_R) * u;

type Node = { code: string; ax: number; ay: number; x: number; y: number; r: number; primary: boolean };

/** Clusters sit on their country, then push apart where they would overlap
 *  (Europe), held back towards home by a spring. A leader line marks any that
 *  moved. Deterministic: same data, same picture. */
function relax(nodes: Node[], w: number, h: number): Node[] {
  const gap = 3;
  const separate = () => {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const p = nodes[i], q = nodes[j];
        let dx = q.x - p.x, dy = q.y - p.y;
        let d = Math.hypot(dx, dy);
        const min = p.r + q.r + gap;
        if (d >= min) continue;
        if (d < 1e-6) { dx = 1; dy = 0; d = 1; }
        const push = (min - d) / 2;
        p.x -= (dx / d) * push; p.y -= (dy / d) * push;
        q.x += (dx / d) * push; q.y += (dy / d) * push;
      }
    }
  };
  for (let it = 0; it < 200; it++) {
    separate();
    for (const n of nodes) { n.x += (n.ax - n.x) * 0.06; n.y += (n.ay - n.y) * 0.06; }
  }
  for (let it = 0; it < 40; it++) separate();   // end on no overlap, not on the spring
  for (const n of nodes) {
    n.x = Math.min(w - n.r - 1, Math.max(n.r + 1, n.x));
    n.y = Math.min(h - n.r - 1, Math.max(n.r + 1, n.y));
  }
  return nodes;
}

function arc(p: { x: number; y: number }, q: { x: number; y: number }): string {
  const dx = q.x - p.x, dy = q.y - p.y, len = Math.hypot(dx, dy) || 1;
  let nx = -dy / len, ny = dx / len;
  if (ny > 0) { nx = -nx; ny = -ny; }       // always bow upward, so crossings stay legible
  const bend = Math.min(len * 0.24, 90);
  const cx = (p.x + q.x) / 2 + nx * bend, cy = (p.y + q.y) / 2 + ny * bend;
  return `M${p.x.toFixed(1)},${p.y.toFixed(1)}Q${cx.toFixed(1)},${cy.toFixed(1)} ${q.x.toFixed(1)},${q.y.toFixed(1)}`;
}

const utc = (s: number) => new Date(s * 1000).toISOString().slice(0, 16).replace('T', ' ');
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ─────────────────────────────── component ────────────────────────────────── */

const PLAY_MS = 14000;     // the whole capture, replayed
const EVENT_SHARE = 0.75;  // of playback time, shared equally between lead arrivals

/** Replay pacing. Most leads first transact in the capture's first week, so a
 *  replay linear in time shows everything in two seconds and then nothing. The
 *  AXIS stays linear in time; only the playback dwells where arrivals are dense:
 *  each gap between consecutive arrivals gets an equal slice of 75% of the
 *  playback, and the other 25% follows real elapsed time. */
function pacing(times: number[], lo: number, hi: number) {
  const ev = [...new Set([lo, ...times, hi])].sort((a, b) => a - b);
  const k = ev.length - 1;
  const cum = [0];
  for (let i = 0; i < k; i++) {
    cum.push(cum[i] + EVENT_SHARE / k + (1 - EVENT_SHARE) * ((ev[i + 1] - ev[i]) / (hi - lo)));
  }
  const find = (xs: number[], v: number) => {
    let i = 0;
    while (i < k - 1 && xs[i + 1] < v) i++;
    return i;
  };
  return {
    timeAt: (s: number) => {                // playback fraction -> capture time
      const i = find(cum, s), f = (s - cum[i]) / (cum[i + 1] - cum[i] || 1);
      return ev[i] + Math.min(1, Math.max(0, f)) * (ev[i + 1] - ev[i]);
    },
    fractionAt: (t: number) => {            // capture time -> playback fraction
      const i = find(ev, t), f = (t - ev[i]) / (ev[i + 1] - ev[i] || 1);
      return cum[i] + Math.min(1, Math.max(0, f)) * (cum[i + 1] - cum[i]);
    },
  };
}
const SCAN_MS = 1500;      // the opening sweep

type Tip = { x: number; y: number; body: ReactNode };

export default function MapView({ onCountry, onOpen }: {
  onCountry: (code: string) => void; onOpen: (entity: string) => void;
}) {
  const [data, setData] = useState<GeoData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.geo().then(setData).catch((e) => setErr(String(e))); }, []);

  const [mode, setMode] = useState<Mode>('all');
  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<Tip | null>(null);
  const reduced = useMemo(reducedMotion, []);

  // Width drives the projection. Measured, never assumed.
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    let raf = 0;
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setWidth(Math.round(el.clientWidth)));
    });
    ro.observe(el);
    setWidth(Math.round(el.clientWidth));
    return () => { ro.disconnect(); cancelAnimationFrame(raf); };
  }, [data]);

  const leads = data?.leads ?? [];
  const full = useMemo(() => tally(leads), [leads]);
  const primaryCodes = useMemo(() => [...full.keys()].sort(), [full]);
  const secondaryCodes = useMemo(() => {
    const s = new Set<string>();
    for (const l of leads) for (const c of l.countries) if (!full.has(c)) s.add(c);
    return [...s].sort();
  }, [leads, full]);

  /* ---- geometry: recomputed only when the width changes ---- */
  const geo = useMemo(() => {
    if (width < 240 || !data) return null;
    const pad = 6;
    const proj = geoNaturalEarth1().fitWidth(width - 2 * pad, SPHERE);
    const [[, y0], [, y1]] = geoPath(proj).bounds(LAND_FC);
    const [tx, ty] = proj.translate();
    proj.translate([tx + pad, ty - y0 + pad]);
    const height = Math.ceil(y1 - y0 + 2 * pad);
    const path = geoPath(proj).digits(1);
    const u = unitFor(width);

    const shapes = new Map<string, string>();
    const nodes: Node[] = [];
    for (const code of [...primaryCodes, ...secondaryCodes]) {
      const sh = shapesOf(code);
      const primary = full.has(code);
      if (primary && sh.length) {
        shapes.set(code, path({ type: 'FeatureCollection', features: sh } as FeatureCollection) ?? '');
      }
      const ll = anchorOf(sh);
      const p = ll ? proj(ll) : null;
      if (!p) continue;                     // listed in the table as "not on the map"
      nodes.push({ code, ax: p[0], ay: p[1], x: p[0], y: p[1], primary,
                   r: primary ? clusterR(full.get(code)!.leads, u) : 3.2 * u });
    }
    return {
      width, height, shapes, u,
      nodes: new Map(relax(nodes, width, height).map((n) => [n.code, n])),
      sphere: path(SPHERE) ?? '',
      graticule: path(GRATICULE) ?? '',
      land: path(LAND_FC) ?? '',
      borders: path(BORDERS) ?? '',
    };
  }, [width, data, primaryCodes, secondaryCodes, full]);

  /* ---- the opening scan: lights the map west to east, once ---- */
  const [scanX, setScanX] = useState<number>(reduced ? Infinity : -1);
  const scanned = scanX === Infinity;
  useEffect(() => {
    if (!geo || scanned) return;
    let raf = 0, start = 0;
    const tick = (t: number) => {
      if (!start) start = t;
      const p = Math.min(1, (t - start) / SCAN_MS);
      const eased = 1 - Math.pow(1 - p, 3);
      setScanX(p >= 1 ? Infinity : eased * (geo.width + 40));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    // rAF sleeps in a hidden tab; the map must still arrive whole.
    const done = window.setTimeout(() => setScanX(Infinity), SCAN_MS + 400);
    return () => { cancelAnimationFrame(raf); window.clearTimeout(done); };
  }, [geo !== null, scanned]);

  /* ---- replay: each lead appears at its first transaction ---- */
  const span = useMemo(() => {
    const ts = leads.map((l) => l.first_ts).filter((t): t is number => t != null);
    if (ts.length < 2) return null;
    const lo = Math.min(...ts), hi = Math.max(...ts);
    return hi > lo ? { lo, hi, ...pacing(ts, lo, hi) } : null;
  }, [leads]);
  const [at, setAt] = useState<number | null>(null);          // null = the whole run
  const [playing, setPlaying] = useState(false);
  const fillRef = useRef<HTMLDivElement>(null);
  const atRef = useRef<number | null>(null);
  atRef.current = at;

  useEffect(() => {
    if (!playing || !span) return;
    let raf = 0, last = 0;
    const from = atRef.current == null || atRef.current >= span.hi ? span.lo : atRef.current;
    let s = span.fractionAt(from), t = from;
    let shown = -1, stamp = 0;
    setAt(t);
    const tick = (now: number) => {
      const dt = last ? Math.min(64, now - last) : 16;
      last = now;
      s = Math.min(1, s + dt / PLAY_MS);
      t = s >= 1 ? span.hi : span.timeAt(s);
      if (fillRef.current) fillRef.current.style.width = `${((t - span.lo) / (span.hi - span.lo)) * 100}%`;
      // React re-renders only when a lead appears, or ~8x a second for the clock.
      const n = leads.reduce((k, l) => k + (l.first_ts == null || l.first_ts <= t ? 1 : 0), 0);
      if (n !== shown || now - stamp > 120) { shown = n; stamp = now; setAt(t); }
      if (t < span.hi) raf = requestAnimationFrame(tick);
      else { setAt(span.hi); setPlaying(false); }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, span, leads]);

  // A finished replay settles back to the whole run - the numbers must land.
  useEffect(() => {
    if (playing || !span || at == null || at < span.hi) return;
    const id = window.setTimeout(() => setAt(null), 900);
    return () => window.clearTimeout(id);
  }, [playing, span, at]);

  const visible = useMemo(
    () => (at == null ? leads : leads.filter((l) => l.first_ts == null || l.first_ts <= at)),
    [leads, at]);
  const now = useMemo(() => tally(visible), [visible]);
  const links = useMemo(() => linksOf(visible), [visible]);
  const secondaryNow = useMemo(() => {
    const m = new Map<string, number>();
    for (const l of visible) for (const c of l.countries) if (!full.has(c)) m.set(c, (m.get(c) ?? 0) + 1);
    return m;
  }, [visible, full]);

  const max = useMemo(() => Math.max(0, ...[...full.values()].map((t) => valueOf(t, mode))), [full, mode]);
  const isLit = useCallback((code: string) => {
    const n = geo?.nodes.get(code);
    return scanned || (n != null && n.ax <= scanX);
  }, [geo, scanned, scanX]);

  /* ---- tooltips ---- */
  const place = (e: { clientX: number; clientY: number }) => {
    const r = wrapRef.current?.getBoundingClientRect();
    return r ? { x: e.clientX - r.left, y: e.clientY - r.top } : { x: 0, y: 0 };
  };
  const countryTip = (code: string): ReactNode => {
    const t = now.get(code), fullT = full.get(code);
    const via = secondaryNow.get(code) ?? 0;
    const partners = links.filter((k) => k.a === code || k.b === code)
      .map((k) => (k.a === code ? k.b : k.a)).slice(0, 4);
    return (
      <>
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-ink">{fmt.country(code)}</span>
          <span className="mono text-2xs text-ink-dim">{code}</span>
        </div>
        {fullT ? (
          <div className="mt-1 space-y-0.5">
            <div><span className="mono font-semibold text-fusion">{t?.leads ?? 0}</span>
              {at != null && <span className="text-ink-dim"> of {fullT.leads}</span>} lead{(t?.leads ?? 0) === 1 ? '' : 's'} whose top-ranked announcing IP is here</div>
            <div className="text-ink-soft">
              <span className="mono">{t?.exit ?? 0}</span> via VPN or Tor exit ·{' '}
              <span className="mono">{t?.hosting ?? 0}</span> hosting ·{' '}
              <span className="mono">{t?.own ?? 0}</span> residential or mobile
            </div>
            <div className="text-ink-soft"><span className="mono">{t?.named ?? 0}</span> named by the engine</div>
          </div>
        ) : (
          <div className="mt-1 text-ink-soft">
            No lead's top-ranked IP is here; <span className="mono">{via}</span> lead{via === 1 ? '' : 's'} also announced through an IP here.
          </div>
        )}
        {partners.length > 0 && (
          <div className="mt-1 text-ink-soft">shares leads with {partners.map((c) => fmt.country(c)).join(', ')}</div>
        )}
        {fullT && <div className="mt-1 text-2xs text-ink-dim">click to open these leads in the queue</div>}
      </>
    );
  };
  const leadTip = (l: GeoLead): ReactNode => (
    <>
      <div className="flex items-baseline gap-2">
        <span className="mono font-semibold text-ink">{l.entity}</span>
        <span className="text-2xs text-ink-dim">rank <span className="mono">{l.rank}</span></span>
      </div>
      <div className="mt-1 text-ink-soft">
        confidence <span className="mono text-fusion">{fmt.conf(l.confidence)}</span> ·{' '}
        {l.asn_type ? `${l.asn_type} IP` : 'no IP type'} in {fmt.country(l.country)}
      </div>
      {EXIT.has(l.asn_type) && (
        <div className="text-ink-soft">an exit relay: the country is the exit's, not the person's</div>
      )}
      {l.first_ts != null && <div className="text-2xs text-ink-dim mt-1">first transaction {utc(l.first_ts)} UTC</div>}
      <div className="text-2xs text-ink-dim">click to open the case file</div>
    </>
  );

  /* ---- keyboard / pointer helpers ---- */
  const enterCountry = (code: string) => (e: RPointerEvent) => { setHover(code); setTip({ ...place(e), body: countryTip(code) }); };
  const moveTip = (e: RPointerEvent) => setTip((t) => (t ? { ...t, ...place(e) } : t));
  const leave = () => { setHover(null); setTip(null); };
  const keyOpen = (fn: () => void) => (e: RKeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn(); }
  };

  /* ---- scrubber ---- */
  const trackRef = useRef<HTMLDivElement>(null);
  const seek = (clientX: number) => {
    if (!span || !trackRef.current) return;
    const r = trackRef.current.getBoundingClientRect();
    const p = Math.min(1, Math.max(0, (clientX - r.left) / r.width));
    setPlaying(false);
    setAt(span.lo + p * (span.hi - span.lo));
  };
  const progress = span && at != null ? (at - span.lo) / (span.hi - span.lo) : 1;
  useEffect(() => {        // keep the bar honest whenever React sets the time
    if (fillRef.current) fillRef.current.style.width = `${progress * 100}%`;
  }, [progress]);

  /* ---- render ---- */
  if (err) return <div className="p-4"><Notice title="Could not load the map" layer="danger">{err}</Notice></div>;
  if (!data) return <div className="p-8"><Spinner label="drawing the map…" /></div>;

  const located = data.n_located, total = data.n_leads;
  const viaExit = [...full.values()].reduce((k, t) => k + t.exit, 0);
  const named = [...full.values()].reduce((k, t) => k + t.named, 0);
  const rows = [...full.values()].sort((a, b) =>
    valueOf(b, mode) - valueOf(a, mode) || b.leads - a.leads || a.code.localeCompare(b.code));
  const rowMax = Math.max(1, ...rows.map((t) => valueOf(t, mode)));
  const activeNow = visible.length;

  return (
    <div className="p-3">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 mb-3">
        <h1 className="display text-ink">map</h1>
        <span className="text-sm text-ink-soft">
          Country of the top-ranked IP each lead announced through. For VPN and Tor exits
          this is the exit's country, not the person's.
        </span>
      </div>

      {/* The run in four numbers, each landing on its value. */}
      <div className="flex flex-wrap items-end gap-x-8 gap-y-2 mb-3 px-1">
        {([
          [<><Counter value={located} /><span className="text-ink-dim text-md"> / {total}</span></>, 'leads located'],
          [<Counter value={full.size} />, full.size === 1 ? 'country' : 'countries'],
          [<Counter value={viaExit} />, 'via VPN or Tor exits'],
          [<Counter value={named} />, 'named by the engine'],
        ] as [ReactNode, string][]).map(([v, label]) => (
          <div key={label} className="flex flex-col gap-0.5">
            <span className="figure">{v}</span>
            <span className="colhead">{label}</span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_22rem] gap-3">
        {/* ═════════════════════════ the map ═════════════════════════ */}
        <Panel pad={false}>
          <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-rule-soft bg-surface-2">
            <span className="colhead mr-1">shade by</span>
            {MODES.map((m) => (
              <Chip key={m.key} active={mode === m.key} onClick={() => setMode(m.key)}>{m.label}</Chip>
            ))}
          </div>

          <div ref={wrapRef} className="relative" onPointerLeave={leave}>
            {geo ? (
              <svg width={geo.width} height={geo.height} viewBox={`0 0 ${geo.width} ${geo.height}`}
                   className="block select-none" role="group"
                   aria-label={`World map: ${located} of ${total} leads located in ${full.size} countries`}>
                <defs>
                  <clipPath id="map-sphere"><path d={geo.sphere} /></clipPath>
                  <linearGradient id="map-scan" x1="0" x2="1">
                    <stop offset="0" stopColor="var(--ink)" stopOpacity="0" />
                    <stop offset="1" stopColor="var(--ink)" stopOpacity="0.07" />
                  </linearGradient>
                </defs>

                <path d={geo.sphere} fill="var(--surface)" stroke="var(--rule)" strokeWidth={0.75} />
                <path d={geo.graticule} clipPath="url(#map-sphere)" fill="none"
                      stroke="var(--rule-soft)" strokeWidth={0.5} />
                <path d={geo.land} fill="var(--surface-3)" stroke="var(--rule)" strokeWidth={0.6}
                      strokeLinejoin="round" pointerEvents="none" />

                {/* Lead countries: the only interactive land. */}
                {primaryCodes.map((code) => {
                  const d = geo.shapes.get(code);
                  if (!d) return null;
                  const k = isLit(code) ? stepOf(valueOf(now.get(code), mode), max) : -1;
                  return (
                    <path key={code} d={d} className="map-country cursor-pointer"
                          style={{ fill: k < 0 ? 'var(--surface-3)' : stepFill(k) }}
                          stroke="none"
                          tabIndex={0} role="button"
                          aria-label={`${fmt.country(code)}: ${now.get(code)?.leads ?? 0} leads. Open them in the queue.`}
                          onPointerEnter={enterCountry(code)} onPointerMove={moveTip}
                          onPointerLeave={leave} onClick={() => onCountry(code)}
                          onFocus={() => setHover(code)} onBlur={() => setHover(null)}
                          onKeyDown={keyOpen(() => onCountry(code))} />
                  );
                })}
                <path d={geo.borders} fill="none" stroke="var(--surface)" strokeWidth={0.6}
                      strokeLinejoin="round" pointerEvents="none" />
                {hover && geo.shapes.get(hover) && (
                  <path d={geo.shapes.get(hover)} fill="none" stroke="var(--ink)" strokeWidth={1.2}
                        pointerEvents="none" />
                )}

                {/* Shared leads, country to country. */}
                {links.map((k) => {
                  const p = geo.nodes.get(k.a), q = geo.nodes.get(k.b);
                  if (!p || !q || !isLit(k.a) || !isLit(k.b)) return null;
                  const d = arc(p, q);
                  const focus = hover != null && (hover === k.a || hover === k.b);
                  const touch = hover == null || focus;
                  const w = Math.min(3.2, 0.8 + 0.8 * Math.log2(k.n));
                  return (
                    <g key={k.key} className="map-fade" opacity={touch ? 1 : 0.1}>
                      <path d={d} pathLength={1} className="map-draw" fill="none" stroke="var(--network)"
                            strokeWidth={w} strokeLinecap="round"
                            opacity={focus ? 0.9 : k.n > 1 ? 0.55 : 0.3} pointerEvents="none" />
                      {/* A pulse where two countries share several leads, or where
                          the analyst is looking - not on every thread at once. */}
                      {!reduced && (k.n > 1 || focus) && (
                        <circle r={1.7} fill="var(--network)" pointerEvents="none">
                          <animateMotion dur={`${(2.6 + (k.key.length % 5) * 0.35).toFixed(2)}s`}
                                         repeatCount="indefinite" path={d}
                                         keyPoints="0;1;0" keyTimes="0;0.5;1" calcMode="linear" />
                        </circle>
                      )}
                      <path d={d} fill="none" stroke="transparent" strokeWidth={9} className="cursor-help"
                            onPointerEnter={(e) => setTip({ ...place(e), body: (
                              <div><span className="font-semibold text-ink">{fmt.country(k.a)}</span>
                                {' '}and <span className="font-semibold text-ink">{fmt.country(k.b)}</span>:{' '}
                                <span className="mono text-network">{k.n}</span> lead{k.n === 1 ? '' : 's'} announced
                                through IPs in both</div>) })}
                            onPointerMove={moveTip} onPointerLeave={() => setTip(null)} />
                    </g>
                  );
                })}

                {/* Leader lines: a cluster pushed off its country still points home. */}
                {[...geo.nodes.values()].map((n) => {
                  const drawn = n.primary ? now.has(n.code) : secondaryNow.has(n.code);
                  if (!isLit(n.code) || !drawn) return null;
                  const dx = n.x - n.ax, dy = n.y - n.ay, d = Math.hypot(dx, dy);
                  if (d < n.r + 1.5) return null;
                  const ex = n.x - (dx / d) * (n.r + 1), ey = n.y - (dy / d) * (n.r + 1);
                  return (
                    <g key={`lead-${n.code}`} pointerEvents="none">
                      <line x1={n.ax} y1={n.ay} x2={ex} y2={ey} stroke="var(--ink-dim)" strokeWidth={0.7} />
                      <circle cx={n.ax} cy={n.ay} r={1.3} fill="var(--ink-dim)" />
                    </g>
                  );
                })}

                {/* Countries that only carried a secondary announcing IP. */}
                {secondaryCodes.map((code) => {
                  const n = geo.nodes.get(code);
                  if (!n || !isLit(code) || !secondaryNow.get(code)) return null;
                  return (
                    <rect key={code} x={n.x - 2.8 * geo.u} y={n.y - 2.8 * geo.u}
                          width={5.6 * geo.u} height={5.6 * geo.u}
                          className="map-pop cursor-help" fill="var(--surface)" stroke="var(--network)"
                          strokeWidth={1.3}
                          onPointerEnter={enterCountry(code)} onPointerMove={moveTip} onPointerLeave={leave} />
                  );
                })}

                {/* Leads, one dot each, the best-ranked at the heart of the cluster. */}
                {primaryCodes.map((code, ci) => {
                  const n = geo.nodes.get(code);
                  if (!n || !isLit(code)) return null;
                  const mine = leads.filter((l) => l.country === code).sort((a, b) => a.rank - b.rank);
                  const shown = mine.filter((l) => at == null || l.first_ts == null || l.first_ts <= at);
                  if (!shown.length) return null;
                  const dim = hover != null && hover !== code;
                  return (
                    <g key={code} className="map-fade" opacity={dim ? 0.45 : 1}>
                      {!reduced && (
                        <circle cx={n.x} cy={n.y} r={n.r + 2} className="map-ping" fill="none"
                                stroke="var(--fusion)" strokeWidth={1} vectorEffect="non-scaling-stroke"
                                style={{ animationDelay: `${((ci * 0.43) % 2.4).toFixed(2)}s` }}
                                pointerEvents="none" />
                      )}
                      <circle cx={n.x} cy={n.y} r={n.r + 3} fill="transparent" className="cursor-pointer"
                              onPointerEnter={enterCountry(code)} onPointerMove={moveTip}
                              onPointerLeave={leave} onClick={() => onCountry(code)} />
                      {mine.map((l, i) => {
                        if (!shown.includes(l)) return null;
                        const [dx, dy] = slot(i, mine.length, geo.u);
                        const exit = EXIT.has(l.asn_type);
                        return (
                          <g key={l.entity}>
                            {l.status === 'ok' && (
                              <circle cx={n.x + dx} cy={n.y + dy} r={(DOT_R + 1.9) * geo.u} fill="none"
                                      stroke="var(--network)" strokeWidth={1} pointerEvents="none" />
                            )}
                            <circle cx={n.x + dx} cy={n.y + dy} r={DOT_R * geo.u}
                                    className="map-pop cursor-pointer"
                                    fill={exit ? 'var(--surface)' : 'var(--fusion)'}
                                    stroke={exit ? 'var(--fusion)' : 'var(--surface)'}
                                    strokeWidth={exit ? 1.2 : 0.7}
                                    onPointerEnter={(e) => { setHover(code); setTip({ ...place(e), body: leadTip(l) }); }}
                                    onPointerMove={moveTip} onPointerLeave={leave}
                                    onClick={(e) => { e.stopPropagation(); onOpen(l.entity); }} />
                          </g>
                        );
                      })}
                    </g>
                  );
                })}

                {/* The opening scan. */}
                {!scanned && scanX > 0 && (
                  <g pointerEvents="none">
                    <rect x={Math.max(0, scanX - 70)} y={0} width={Math.min(70, scanX)} height={geo.height}
                          fill="url(#map-scan)" />
                    <line x1={scanX} y1={0} x2={scanX} y2={geo.height} stroke="var(--ink-soft)"
                          strokeWidth={1} opacity={0.5} />
                  </g>
                )}
              </svg>
            ) : (
              <div className="h-[28rem] grid place-items-center"><Spinner label="projecting…" /></div>
            )}

            {tip && (
              <div className="absolute z-10 pointer-events-none bg-surface border border-rule px-3 py-2
                              text-sm max-w-[20rem] shadow-none"
                   style={{
                     left: Math.max(0, Math.min(tip.x + 14, (geo?.width ?? 0) - 330)),
                     top: tip.y > (geo?.height ?? 0) - 150 ? tip.y - 14 : tip.y + 14,
                     transform: tip.y > (geo?.height ?? 0) - 150 ? 'translateY(-100%)' : undefined,
                   }}>
                {tip.body}
              </div>
            )}
          </div>

          {/* ---- replay ---- */}
          {span && (
            <div className="flex items-center gap-3 px-4 py-2 border-t border-rule-soft">
              {!reduced && (
                <button onClick={() => setPlaying((p) => !p)}
                        className="mono text-2xs px-2 h-6 border border-ink text-ink hover:bg-surface-3
                                   transition-colors duration-150 cursor-pointer whitespace-nowrap">
                  {playing ? 'pause' : 'replay'}
                </button>
              )}
              <div ref={trackRef} role="slider" tabIndex={0}
                   aria-label="Capture time" aria-valuemin={span.lo} aria-valuemax={span.hi}
                   aria-valuenow={Math.round(at ?? span.hi)} aria-valuetext={`${utc(at ?? span.hi)} UTC`}
                   className="relative flex-1 h-6 cursor-pointer outline-none focus-visible:outline
                              focus-visible:outline-1 focus-visible:outline-ink"
                   onPointerDown={(e) => { trackRef.current?.setPointerCapture(e.pointerId); seek(e.clientX); }}
                   onPointerMove={(e) => { if (e.buttons & 1) seek(e.clientX); }}
                   onKeyDown={(e) => {
                     const step = (span.hi - span.lo) / 40, cur = at ?? span.hi;
                     if (e.key === 'ArrowRight' || e.key === 'ArrowUp') { e.preventDefault(); setPlaying(false); setAt(Math.min(span.hi, cur + step)); }
                     if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') { e.preventDefault(); setPlaying(false); setAt(Math.max(span.lo, cur - step)); }
                     if (e.key === 'Home') { e.preventDefault(); setPlaying(false); setAt(span.lo); }
                     if (e.key === 'End') { e.preventDefault(); setPlaying(false); setAt(null); }
                   }}>
                <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-1 bg-surface-3" />
                <div ref={fillRef} className="absolute left-0 top-1/2 -translate-y-1/2 h-1 bg-fusion"
                     style={{ width: `${progress * 100}%` }} />
                {/* One tick per lead, at its first transaction: the run's rhythm. */}
                {leads.map((l) => l.first_ts == null ? null : (
                  <span key={l.entity} aria-hidden
                        className="absolute top-0 w-px h-2"
                        style={{
                          left: `${((l.first_ts - span.lo) / (span.hi - span.lo)) * 100}%`,
                          background: at == null || l.first_ts <= at ? 'var(--fusion)' : 'var(--rule)',
                        }} />
                ))}
              </div>
              <span className="mono text-2xs text-ink-soft whitespace-nowrap w-[15rem] text-right">
                {at == null
                  ? <>all {total} leads · {utc(span.lo).slice(0, 10)} → {utc(span.hi).slice(0, 10)}</>
                  : <>{utc(at)} UTC · <span className="text-fusion font-semibold">{activeNow}</span> of {total}</>}
              </span>
              {at != null && (
                <button onClick={() => { setPlaying(false); setAt(null); }}
                        className="mono text-2xs px-2 h-6 border border-rule text-ink-soft hover:text-ink
                                   hover:border-ink transition-colors duration-150 cursor-pointer">
                  all
                </button>
              )}
            </div>
          )}

          {/* ---- legend ---- */}
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2 border-t border-rule-soft
                          text-2xs text-ink-soft">
            <span className="flex items-center gap-1">
              <span className="colhead mr-1">leads · {MODES.find((m) => m.key === mode)!.label}</span>
              {stepRanges(max).map((r) => (
                <span key={r.k} className="flex items-center gap-1 mr-1">
                  <span className="inline-block w-3 h-3" style={{ background: stepFill(r.k) }} />
                  <span className="mono">{r.lo === r.hi ? r.lo : `${r.lo}–${r.hi}`}</span>
                </span>
              ))}
              {max === 0 && <span>none in this run</span>}
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="10" height="10" aria-hidden><circle cx="5" cy="5" r="3.2" fill="var(--fusion)" /></svg>
              a lead
            </span>
            <span className="flex items-center gap-1.5">
              <svg width="10" height="10" aria-hidden><circle cx="5" cy="5" r="3" fill="var(--surface)" stroke="var(--fusion)" strokeWidth="1.2" /></svg>
              via a VPN or Tor exit
            </span>
            {named > 0 && (
              <span className="flex items-center gap-1.5">
                <svg width="12" height="12" aria-hidden><circle cx="6" cy="6" r="4.6" fill="none" stroke="var(--network)" /><circle cx="6" cy="6" r="2.6" fill="var(--fusion)" /></svg>
                named by the engine
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <svg width="18" height="8" aria-hidden><path d="M1 6 Q9 0 17 6" fill="none" stroke="var(--network)" strokeWidth="1.4" /></svg>
              same lead announced from both
            </span>
            {secondaryCodes.length > 0 && (
              <span className="flex items-center gap-1.5">
                <svg width="10" height="10" aria-hidden><rect x="2" y="2" width="6" height="6" fill="var(--surface)" stroke="var(--network)" strokeWidth="1.3" /></svg>
                announcing IP only
              </span>
            )}
          </div>
        </Panel>

        {/* ═════════════════════════ the table ═════════════════════════ */}
        <Panel pad={false}>
          <div className="px-4 pt-3">
            <Eyebrow right={at == null ? `${full.size} with leads` : `${now.size} so far`}>countries</Eyebrow>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-rule">
                <th className="colhead text-left px-4 py-1.5">country</th>
                <th className="colhead text-right px-2 py-1.5" title="leads in the current shading">leads</th>
                <th className="colhead text-right px-2 py-1.5" title="via a VPN or Tor exit">exit</th>
                <th className="colhead text-right px-2 py-1.5 whitespace-nowrap" title="residential or mobile">own line</th>
                <th className="colhead text-right pl-2 pr-4 py-1.5" title="named by the engine">named</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const cur = now.get(t.code);
                const v = valueOf(cur, mode);
                const onMap = geo?.nodes.has(t.code) ?? true;
                return (
                  <tr key={t.code}
                      className={`border-b border-rule-soft last:border-0 cursor-pointer transition-colors duration-150
                                  ${hover === t.code ? 'bg-active-wash' : 'hover:bg-surface-2'}`}
                      onMouseEnter={() => setHover(t.code)} onMouseLeave={() => setHover(null)}
                      onClick={() => onCountry(t.code)}>
                    <td className="px-4 py-2">
                      <div className="flex items-baseline gap-2">
                        <button onClick={(e) => { e.stopPropagation(); onCountry(t.code); }}
                                onFocus={() => setHover(t.code)} onBlur={() => setHover(null)}
                                aria-label={`${fmt.country(t.code)}: open ${t.leads} leads in the queue`}
                                className="text-sm text-ink truncate text-left cursor-pointer
                                           focus-visible:outline focus-visible:outline-1 focus-visible:outline-ink">
                          {fmt.country(t.code)}
                        </button>
                        <span className="mono text-2xs text-ink-dim">{t.code}</span>
                        {!onMap && <span className="text-2xs text-ink-dim">· not on the map</span>}
                      </div>
                      <div className="h-1 bg-surface-3 mt-1">
                        <div key={`${mode}-${t.code}`} className="h-full anim-bar transition-[width] duration-300"
                             style={{ width: `${(v / rowMax) * 100}%`, background: 'var(--fusion)' }} />
                      </div>
                    </td>
                    <td className="num mono text-sm font-semibold text-fusion px-2 py-2 align-top">{v}</td>
                    <td className="num mono text-sm text-ink-soft px-2 py-2 align-top">{cur?.exit ?? 0}</td>
                    <td className="num mono text-sm text-ink-soft px-2 py-2 align-top">{cur?.own ?? 0}</td>
                    <td className="num mono text-sm text-ink-soft pl-2 pr-4 py-2 align-top">{cur?.named ?? 0}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-3 border-t border-rule-soft text-2xs text-ink-dim space-y-1">
            {total > located && (
              <p><span className="mono">{total - located}</span> lead{total - located === 1 ? '' : 's'} had no
                announcing IP placed in a country and {total - located === 1 ? 'is' : 'are'} not on the map.</p>
            )}
            <p>Lines join countries whose IPs announced the same lead. Click a country to open its
              leads in the queue, or a dot to open that lead.</p>
          </div>
        </Panel>
      </div>
    </div>
  );
}
