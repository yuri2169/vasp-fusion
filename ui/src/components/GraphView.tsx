/** k-hop link analysis.
 *
 * Cytoscape rather than a hand-rolled force layout: it does incremental layout,
 * pan/zoom, and hit-testing properly, and this is the one view where those are
 * genuinely hard. The subgraph arrives already extracted and node-capped by the
 * server — sending an unbounded neighbourhood to the browser is exactly how
 * link-analysis views die (roadmap §4.4 R4).
 *
 * The node cap is stated in the UI rather than hidden. "Showing 214 of 12,847"
 * is information; silently truncating is a lie of omission.
 *
 * Every channel carries data, none is decoration:
 *   ring      hop distance from the subject
 *   side      left = value received by the subject, right = value sent
 *   arc order value rank, largest on the horizontal axis where the eye lands
 *   size/hue  alert score, stretched over the run's range
 *   width     log value on the edge
 *   motion    dashes marching along the traced path, in the flow direction
 *   time      the scrubber replays edges by the date they first carried value
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape, { type Core } from 'cytoscape';
import { api, fmt, type GraphData } from '../api';
import { Button, Spinner } from '../ui';

/** Resolve the layer palette to literals for Cytoscape.
 *
 * Cytoscape paints to a canvas and cannot consume `var(--chain)`, so the tokens
 * are read off the document at render time. This function is called again when
 * the theme changes; hardcoding the values left the graph in light-theme colours
 * on a dark canvas, with the subject node's label set to the light theme's ink
 * (#0E1C27) on a near-black ground - invisible.
 */
function palette() {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, fallback: string) => cs.getPropertyValue(n).trim() || fallback;
  return {
    ink: v('--ink', '#0E1C27'),
    dim: v('--ink-dim', '#56646F'),
    data: v('--data', '#5C6B78'),
    rule: v('--rule', '#C3CCD4'),
    chain: v('--chain', '#2D6A9F'),
    network: v('--network', '#7B4B94'),
    fusion: v('--fusion', '#B8791C'),
    danger: v('--danger', '#A2453B'),
  };
}

type Edge = GraphData['edges'][number];
type Place = { depth: number; side: 1 | -1; parent: string | null };

/** Breadth-first walk out from the subject.
 *
 * Returns three things per node, all of which the layout spends: how far out it
 * is, which side of the subject it belongs on, and who reached it. The side is
 * decided at the first hop by net value — a counterparty the subject was paid
 * by sits left, one it paid sits right — and inherited outward, so a whole
 * downstream branch stays on the side of the money that created it.
 */
function traverse(edges: Edge[], subject: string): Map<string, Place> {
  const adj = new Map<string, string[]>();
  const link = (a: string, b: string) => adj.set(a, [...(adj.get(a) ?? []), b]);
  edges.forEach((e) => { link(e.src, e.dst); link(e.dst, e.src); });

  const net = new Map<string, number>();
  edges.forEach((e) => {
    if (e.src === subject) net.set(e.dst, (net.get(e.dst) ?? 0) + e.value);
    if (e.dst === subject) net.set(e.src, (net.get(e.src) ?? 0) - e.value);
  });

  const out = new Map<string, Place>([[subject, { depth: 0, side: 1, parent: null }]]);
  let frontier = [subject];
  while (frontier.length) {
    const next: string[] = [];
    for (const n of frontier) {
      const here = out.get(n)!;
      for (const m of adj.get(n) ?? []) {
        if (out.has(m)) continue;
        // Sent to (positive net) goes right, received from goes left. Beyond the
        // first hop there is no direct flow to read, so the branch inherits.
        const side = here.depth === 0 ? ((net.get(m) ?? 0) >= 0 ? 1 : -1) : here.side;
        out.set(m, { depth: here.depth + 1, side, parent: n });
        next.push(m);
      }
    }
    frontier = next;
  }
  return out;
}

/** Fixed coordinates for every node, computed rather than laid out.
 *
 * Handed to cytoscape's `preset`, not produced by `concentric`, for two measured
 * reasons. Concentric derives a ring's radius from how many nodes it must hold,
 * so a hub with 61 one-hop neighbours put ring 1 at r=369 and ring 2 at r=407 —
 * two rings 38px apart read as one ring, and `equidistant: true` gave the same
 * radii. And an animated layout's `layoutstop` never fires where rAF is
 * suspended, so a correction applied in that handler silently does not run.
 *
 * Each ring is two arcs with a gap at the top and bottom, so the received/sent
 * split is visible as a shape rather than only as a legend entry.
 */
// Wedges left empty at the top and the bottom, so the received/sent split is
// visible as a break in the ring rather than only as a legend entry.
const GAP = 13 * (Math.PI / 180);

// The panel is roughly twice as wide as it is tall (measured: 671 x 329), and a
// circular layout fits to the short side - it left half the width empty and shrank
// the graph to zoom 0.26. Elliptical rings keep the hop ordering and spend the
// space. Nodes bunch a little at the top and bottom of an ellipse, which is where
// the smallest flows are seated, and spread where the largest ones are.
const ASPECT = 1.7;

function positions(
  place: Map<string, { depth: number; side: 1 | -1 }>,
  weight: Map<string, number>,
) {
  const arcs = new Map<string, string[]>();          // `${depth}:${side}` -> ids
  place.forEach((p, id) => {
    if (p.depth === 0) return;
    const k = `${p.depth}:${p.side}`;
    arcs.set(k, [...(arcs.get(k) ?? []), id]);
  });

  const depths = [...new Set([...place.values()].map((p) => p.depth))]
    .filter((d) => d > 0).sort((a, b) => a - b);

  const usable = 2 * Math.PI - 2 * GAP;
  const pos = new Map<string, { x: number; y: number }>();
  place.forEach((p, id) => { if (p.depth === 0) pos.set(id, { x: 0, y: 0 }); });

  let prev = 0;
  for (const d of depths) {
    const right = arcs.get(`${d}:1`) ?? [];
    const left = arcs.get(`${d}:-1`) ?? [];
    const n = right.length + left.length;
    if (!n) continue;

    // Each half gets arc in proportion to what it holds. A fixed half each is
    // what a symmetric entity wants, but a fan-out with 60 outbound and 1
    // inbound counterparty then crams 60 nodes into 180 degrees and leaves the
    // other half blank - measured: it pushed ring 1 from r=250 out to r=591 and
    // shoved the subject to the edge of the panel.
    const share = (k: number) => (usable * k) / n;
    // A ring needs 26px of arc per node and at least 100px of clear water
    // outside the ring within it, so hop distance stays readable even when one
    // ring holds sixty nodes and the next holds three. The 420px ceiling on a
    // single step is what keeps three hops usable: ring 3 of this subject holds
    // 461 nodes, whose honest arc length puts it at r=2056 and drives the whole
    // view to minZoom, where the inner rings are an unreadable smudge. Past that
    // point crowding one ring beats shrinking every ring.
    prev = Math.max(prev + 100, Math.min((n * 26) / usable, prev + 420));

    for (const [ids, side] of [[right, 1], [left, -1]] as [string[], number][]) {
      if (!ids.length) continue;
      // Biggest flows first, laid out from the middle of the arc outward, so the
      // largest counterparties sit on the horizontal axis where the eye lands
      // and the tail runs away towards the quiet top and bottom of the ring.
      const ordered = [...ids].sort((a, b) => (weight.get(b) ?? 0) - (weight.get(a) ?? 0));
      const seats: string[] = [];
      ordered.forEach((id, i) => (i % 2 ? seats.unshift(id) : seats.push(id)));

      const span = share(ids.length);
      const centre = side > 0 ? 0 : Math.PI;
      seats.forEach((id, i) => {
        const t = seats.length === 1 ? 0.5 : i / (seats.length - 1);
        const a = centre + (-span / 2 + t * span) * side;
        pos.set(id, { x: prev * ASPECT * Math.cos(a), y: prev * Math.sin(a) });
      });
    }
  }

  return { pos, outer: prev };
}

const reducedMotion = () =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Date and time, always. A layering burst opens its edges inside hours, so a
 *  day-resolution readout prints the same string for the whole useful travel of
 *  the scrubber - measured: all 19 births on this neighbourhood read 2026-06-01.
 */
const stamp = (epoch: number) =>
  new Date(epoch * 1000).toISOString().slice(0, 16).replace('T', ' ');

export function GraphView({ entity }: { entity: string }) {
  const box = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [data, setData] = useState<GraphData | null>(null);
  const [hops, setHops] = useState(2);
  const [sel, setSel] = useState<
    { id: string; kind: string; score: number; depth: number; side: number } | null>(null);
  // The PS names IPs, WALLETS and transactions. Entity supernodes are the right
  // default; the address and transaction layers beneath are one click away.
  const [expanded, setExpanded] = useState(false);
  const [sub, setSub] = useState<{
    addresses: { address: string }[];
    transactions: { txid: string; ts: string; value: number }[];
    truncated: boolean; n_addresses_total: number;
  } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // Time scrubber. `step === null` means "all of it" — the graph is untimed
  // until the analyst asks for a cut, and a run recorded before entity_edges
  // carried timestamps has no scrubber at all rather than a broken one.
  const [step, setStep] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  // Cytoscape resolves the palette once at paint time, so a theme change has to
  // force a rebuild - otherwise the graph keeps the colours of whichever theme
  // was active when the case file opened.
  const [themeTick, setThemeTick] = useState(0);
  useEffect(() => {
    const obs = new MutationObserver(() => setThemeTick((n) => n + 1));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onMq = () => setThemeTick((n) => n + 1);
    mq.addEventListener('change', onMq);
    return () => { obs.disconnect(); mq.removeEventListener('change', onMq); };
  }, []);

  useEffect(() => {
    let live = true;
    setData(null); setSel(null); setStep(null); setPlaying(false);
    api.graph(entity, hops)
      .then((g) => live && setData(g))
      .catch((e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [entity, hops]);

  useEffect(() => {
    if (!expanded) { setSub(null); return; }
    let live = true;
    api.expand(entity).then((r) => live && setSub(r)).catch(() => {});
    return () => { live = false; };
  }, [expanded, entity]);

  // The scrubber advances by edge birth, not by wall clock. Measured on this
  // neighbourhood: 77 of 79 edges opened inside four days and two stragglers
  // arrived 25 days later, so a linear time axis spends 90% of its travel
  // showing nothing. Stepping through the births makes every position reveal an
  // edge, and the readout still prints the real timestamp - so the jump from
  // 06-05 to 06-30 at the far end is visible as the finding it is.
  const births = useMemo(() => {
    const ts = (data?.edges ?? [])
      .map((e) => e.first_ts).filter((v): v is number => v != null);
    return [...new Set(ts)].sort((a, b) => a - b);
  }, [data]);
  const timed = births.length > 1;
  const cut = step == null ? null : births[Math.min(step, births.length - 1)];

  // setInterval, not rAF: a rAF-driven playhead stalls in a hidden tab and
  // strands the graph mid-replay showing a time that never advances.
  useEffect(() => {
    if (!playing || !timed) return;
    const id = setInterval(() => {
      setStep((cur) => {
        const next = (cur ?? -1) + 1;
        if (next >= births.length - 1) { setPlaying(false); return null; }
        return next;
      });
    }, 55);
    return () => clearInterval(id);
  }, [playing, timed, births]);

  // The reachability walk is what the layout, the ring labels and the traced
  // path all read, so it is computed once per payload rather than per render.
  const place = useMemo(
    () => (data ? traverse(data.edges, entity) : new Map<string, Place>()),
    [data, entity]);

  useEffect(() => {
    if (!data || !box.current) return;
    cy.current?.destroy();

    // Calibrated scores saturate near 1 (measured: 0.9608..0.9987 over 60
    // alerts), so the raw 0..1 range would paint every alerted node the same
    // colour. Stretch over the run's observed range instead — from the run, not
    // from this subgraph, so the hue means the same thing on every case file.
    const { score_lo: lo = 0, score_hi: hi = 1 } = data.meta;
    const risk = (s: number) =>
      hi - lo < 1e-6 ? 0.5 : Math.max(0, Math.min(1, (s - lo) / (hi - lo)));
    const maxValue = Math.max(1, ...data.edges.map((e) => e.value));

    // Total value on a node's edges — what decides its seat within its arc.
    const weight = new Map<string, number>();
    data.edges.forEach((e) => {
      weight.set(e.src, (weight.get(e.src) ?? 0) + e.value);
      weight.set(e.dst, (weight.get(e.dst) ?? 0) + e.value);
    });

    const maxD = Math.max(0, ...[...place.values()].map((p) => p.depth));
    const layoutOf = new Map<string, { depth: number; side: 1 | -1 }>();
    data.nodes.forEach((n) => {
      const p = place.get(n.id);
      layoutOf.set(n.id, { depth: p?.depth ?? maxD, side: p?.side ?? 1 });
    });
    // The subject's own wallets and transactions ring outside the entities, one
    // layer each, split left/right only to keep the two arcs balanced.
    sub?.addresses.forEach((a, i) =>
      layoutOf.set(a.address, { depth: maxD + 1, side: i % 2 ? 1 : -1 }));
    sub?.transactions.forEach((x, i) =>
      layoutOf.set(x.txid, { depth: maxD + 2, side: i % 2 ? 1 : -1 }));
    const { pos } = positions(layoutOf, weight);
    const at = (id: string) => pos.get(id) ?? { x: 0, y: 0 };

    const elements = [
      // Wallets and transactions hang off the subject by a MEMBERSHIP edge —
      // entity_addresses / entity_txs say these belong to this entity, and that
      // is all they say. An earlier version drew address->transaction edges from
      // a cartesian product of the two lists; those links were fabricated.
      ...(sub ? sub.addresses.map((a) => ({
        data: { id: a.address, kind: 'address', label: a.address.slice(0, 10) },
        position: at(a.address),
      })) : []),
      ...(sub ? sub.transactions.map((x) => ({
        data: { id: x.txid, kind: 'tx', label: x.txid.slice(0, 10), value: x.value },
        position: at(x.txid),
      })) : []),
      ...(sub ? [...sub.addresses.map((a) => a.address),
                 ...sub.transactions.map((x) => x.txid)].map((id, i) => ({
        data: { id: `m${i}`, source: entity, target: id, membership: 1 },
      })) : []),
      ...data.nodes.map((n) => {
        const p = place.get(n.id);
        return {
          data: {
            id: n.id, subject: n.subject, alerted: n.alerted,
            kind: 'entity', score: n.score, risk: risk(n.score),
            depth: p?.depth ?? maxD, side: p?.side ?? 1,
            label: n.subject ? n.id : n.id.replace(/^ENT-/, ''),
          },
          position: at(n.id),
        };
      }),
      ...data.edges.map((e, i) => ({
        data: {
          id: `e${i}`, source: e.src, target: e.dst, value: e.value, n_tx: e.n_tx,
          first_ts: e.first_ts ?? null,
          // log, because payment values span orders of magnitude and a linear
          // width mapping renders every edge but the largest as a hairline.
          w: 0.8 + 2.6 * (Math.log1p(e.value) / Math.log1p(maxValue)),
        },
      })),
    ];

    const P = palette();
    const inst = cytoscape({
      container: box.current,
      elements,
      // Square-ish, flat, no glow — the same restraint as the rest of the app.
      style: [
        { selector: 'node', style: {
          'background-color': P.dim, width: 9, height: 9,
          label: '', 'border-width': 0,
        } },
        { selector: 'node[?alerted]', style: {
          'background-color': `mapData(risk, 0, 1, ${P.fusion}, ${P.danger})`,
          width: 'mapData(risk, 0, 1, 11, 21)' as unknown as number,
          height: 'mapData(risk, 0, 1, 11, 21)' as unknown as number,
        } },
        { selector: 'node[?subject]', style: {
          'background-color': P.ink, width: 22, height: 22,
          label: 'data(label)', 'font-family': 'Spline Sans Mono', 'font-size': 9,
          'text-valign': 'center', 'text-halign': 'center', 'text-margin-y': 0,
          color: P.ink,
          // The subject sits inside the spoke fan, so its label needs a ground
          // of its own or it is unreadable over the edges.
          'text-background-color': P.rule, 'text-background-opacity': 0.92,
          'text-background-padding': '3px',
        } },
        { selector: 'edge', style: {
          width: 'data(w)' as unknown as number,
          'line-color': P.rule, 'curve-style': 'straight',
          'target-arrow-shape': 'triangle', 'target-arrow-color': P.rule,
          'arrow-scale': 0.5,
          // A hub with sixty spokes converging on one point paints a solid fan
          // at full opacity and buries both the subject and the traced path.
          opacity: 0.55,
        } },
        // Wallet and transaction nodes are shaped differently, not just tinted,
        // so the three layers stay distinguishable without relying on colour.
        { selector: 'node[kind = "address"]', style: {
          'background-color': P.chain, width: 8, height: 8, shape: 'rectangle',
        } },
        { selector: 'node[kind = "tx"]', style: {
          'background-color': P.data, width: 7, height: 7, shape: 'diamond',
        } },
        // Membership lines were 0.6px dotted at 0.55 opacity and invisible on
        // both grounds. Solid and in the layer's own colour now - but held below
        // the payment edges, because forty-six structural spokes at full
        // strength out-shout the flows they are only the backdrop to.
        { selector: 'edge[?membership]', style: {
          width: 0.8, 'line-color': P.data, 'line-style': 'solid',
          'target-arrow-shape': 'none', opacity: 0.5,
        } },
        // The traced path: straight, like every other edge. Bending it was meant
        // to lift it clear of the spokes it crosses; what it actually did was
        // turn six overlapping arcs into a knot at the hub, exactly where the
        // subject sits and where the picture has to be readable. Colour, weight
        // and motion separate it from the neighbourhood perfectly well without
        // moving the geometry away from the money it represents.
        { selector: '.path', style: {
          'line-color': P.network, 'target-arrow-color': P.network,
          'curve-style': 'straight',
          'line-style': 'dashed', 'line-dash-pattern': [6, 5],
          width: 'mapData(w, 0.8, 3.4, 2, 4.5)' as unknown as number,
          'arrow-scale': 1, 'z-index': 20, opacity: 1,
        } },
        { selector: 'node.on-path', style: {
          'border-width': 2, 'border-color': P.network, 'z-index': 21,
        } },
        // Hover focus: the neighbourhood keeps its ink and gains its labels,
        // everything else drops back. Turns a hairball into one local story.
        { selector: '.faded', style: { opacity: 0.08, 'text-opacity': 0 } },
        { selector: 'node.focus', style: {
          label: 'data(label)', 'font-family': 'Spline Sans Mono', 'font-size': 8,
          'text-valign': 'bottom', 'text-margin-y': 4, color: P.ink,
          'text-background-color': P.rule, 'text-background-opacity': 0.3,
          'text-background-padding': '2px',
        } },
        // Not yet in the scrubber's window. display:none rather than opacity so
        // hidden edges cannot be hovered or traced through.
        { selector: '.unborn', style: { display: 'none' } },
        { selector: 'node:selected', style: {
          'border-width': 2, 'border-color': P.chain,
        } },
      ],
      layout: { name: 'preset', fit: true, padding: 26 },
      wheelSensitivity: 0.25,
      minZoom: 0.15, maxZoom: 3,
    });

    /** Trace subject -> id along the BFS tree and mark it. */
    const trace = (id: string | null) => {
      inst.elements().removeClass('path on-path');
      if (!id || id === entity) {
        // Nothing selected: the default trace is the subject's largest flows,
        // which is the question the case file opens on.
        inst.$(`#${CSS.escape(entity)}`).connectedEdges().not('[?membership]')
          .sort((a, b) => (b.data('value') ?? 0) - (a.data('value') ?? 0))
          .slice(0, 6).addClass('path');
        return;
      }
      const chain: string[] = [];
      for (let n: string | null = id; n; n = place.get(n)?.parent ?? null) chain.push(n);
      chain.forEach((n) => inst.$(`#${CSS.escape(n)}`).addClass('on-path'));
      for (let i = 0; i + 1 < chain.length; i++) {
        inst.$(`#${CSS.escape(chain[i])}`).edgesWith(`#${CSS.escape(chain[i + 1])}`)
          .not('[?membership]').addClass('path');
      }
    };
    trace(null);

    // Cytoscape caches the container's dimensions at construction and only
    // recomputes on resize(). The case file's right column has not laid out
    // when this mounts, so it cached width 0 - measured: the div is 671px wide
    // while cy.width() reports 0, which is why the graph drew at zoom 1 in the
    // top-left corner instead of filling its panel. The observer covers mount,
    // panel resize and window resize in one place.
    const ro = new ResizeObserver(() => { inst.resize(); inst.fit(undefined, 26); });
    ro.observe(box.current);

    inst.on('mouseover', 'node', (evt) => {
      const near = evt.target.closedNeighborhood();
      inst.elements().difference(near).addClass('faded');
      near.nodes().addClass('focus');
    });
    inst.on('mouseout', 'node', () => inst.elements().removeClass('faded focus'));
    inst.on('tap', 'node', (evt) => {
      const n = evt.target;
      setSel({
        id: n.id(), kind: n.data('kind') ?? 'entity', score: n.data('score') ?? 0,
        depth: n.data('depth') ?? -1, side: n.data('side') ?? 0,
      });
      trace(n.data('kind') === 'entity' ? n.id() : null);
    });
    inst.on('tap', (evt) => {
      if (evt.target === inst) { setSel(null); trace(null); }
    });

    // Dashes march toward the arrowhead, so the animation states the direction
    // of the money rather than merely being alive.
    // ponytail: style bypass per frame over the traced path only (a handful of
    // edges). If the trace ever covers the whole graph, move it to an overlay.
    let raf = 0;
    if (!reducedMotion()) {
      let offset = 0;
      const tick = () => {
        offset -= 0.55;
        inst.$('.path').style('line-dash-offset', offset);
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      // Settle on arrival: the viewport eases in, never the node positions.
      // Positions are already final, so if rAF is suspended the graph is simply
      // there rather than stranded halfway through a layout that never ran.
      inst.zoom(inst.zoom() * 0.82);
      inst.animate({ fit: { eles: inst.elements(), padding: 26 } }, { duration: 380 });
    }

    cy.current = inst;
    return () => { ro.disconnect(); cancelAnimationFrame(raf); inst.destroy(); cy.current = null; };
  }, [data, entity, sub, themeTick, place]);

  // Scrubbing only toggles a class; rebuilding the graph per slider step would
  // relay out and refit sixty times a second.
  useEffect(() => {
    const inst = cy.current;
    if (!inst) return;
    inst.batch(() => {
      inst.edges('[!membership]').forEach((e) => {
        const born = e.data('first_ts');
        e.toggleClass('unborn', cut != null && born != null && born > cut);
      });
      inst.nodes('[kind = "entity"]').forEach((n) => {
        n.toggleClass('unborn',
          cut != null && !n.data('subject')
          && n.connectedEdges('[!membership]').not('.unborn').length === 0);
      });
    });
  }, [cut, data, sub]);

  if (err) return <div className="p-4 text-sm text-danger">{err}</div>;

  const swatch = (v: string, l: string) => (
    <span key={l} className="mono text-2xs text-ink-soft flex items-center gap-2">
      <span className="w-2.5 h-2.5 inline-block" style={{ background: `var(${v})` }} />{l}
    </span>
  );



  return (
    <div>
      <div className="flex items-center gap-2 px-4 pb-2">
        <span className="mono text-2xs text-ink-dim">
          {data ? <>showing <b className="text-ink">{fmt.int(data.meta.nodes_shown)}</b> nodes
            · {fmt.int(data.edges.length)} edges · {data.meta.hops} hop{data.meta.hops > 1 ? 's' : ''}
            {data.meta.capped ? <span className="text-fusion"> · capped</span> : null}
            {sub ? <span className="text-chain"> · {sub.addresses.length} of {sub.n_addresses_total} wallets
              · {sub.transactions.length} transactions</span> : null}</>
            : 'extracting subgraph…'}
        </span>
        <div className="ml-auto flex items-center gap-2 no-print">
          {[1, 2, 3].map((h) => (
            <button key={h} onClick={() => setHops(h)} aria-pressed={hops === h}
                    className="mono text-2xs w-7 h-6 border transition-colors duration-150 cursor-pointer"
                    style={hops === h
                      ? { borderColor: 'var(--chain)', color: 'var(--chain)', background: 'var(--chain-wash)' }
                      : { borderColor: 'var(--rule)', color: 'var(--ink-soft)' }}>
              {h}h
            </button>
          ))}
          {/* One word: the longer label wrapped this button onto a second line
              and pushed the panel header taller whenever the status text grew. */}
          <Button variant={expanded ? 'default' : 'ghost'}
                  onClick={() => setExpanded(!expanded)}
                  title="Show the constituent wallets and transactions of this entity">
            wallets
          </Button>
          <Button variant="ghost" onClick={() => cy.current?.fit(undefined, 24)}>fit</Button>
          {/* For Gephi, yEd, Maltego or i2: the same subgraph plus announcing IPs. */}
          {(['graphml', 'csv'] as const).map((f) => (
            <a key={f} href={api.graphExportUrl(entity, f, hops)} download
               title={f === 'graphml' ? 'Download for Gephi, yEd, Maltego or i2' : 'Download as a CSV edge list'}
               className="mono text-2xs px-2 h-6 inline-flex items-center border border-rule
                          text-ink-soft hover:text-ink hover:border-ink transition-colors duration-150">
              {f === 'graphml' ? 'GraphML' : 'CSV'}
            </a>
          ))}
        </div>
      </div>

      <div className="relative border-t border-rule bg-surface-2" style={{ height: 330 }}>
        {!data && (
          <div className="absolute inset-0 grid place-items-center">
            <Spinner label="laying out graph…" />
          </div>
        )}
        <div ref={box} className="w-full h-full" />

        {/* Which half is which. Stated on the canvas, because a reader who has
            to look it up in the legend will not look it up. */}
        {data && (
          <>
            <span className="mono text-2xs text-ink-dim absolute top-2 left-3 no-print">
              ← received from
            </span>
            <span className="mono text-2xs text-ink-dim absolute top-2 right-3 no-print">
              sent to →
            </span>
          </>
        )}

        {sel && (
          <div className="absolute bottom-2 left-2 bg-surface border border-rule px-3 py-2
                          flex items-center gap-3 max-w-[90%]">
            <div className="min-w-0">
              <span className="mono text-2xs text-ink-dim">
                {sel.kind === 'entity' ? 'entity' : sel.kind === 'address' ? 'wallet' : 'transaction'}
                {sel.depth > 0 ? ` · ${sel.depth} hop${sel.depth > 1 ? 's' : ''} ${sel.side > 0 ? 'downstream' : 'upstream'}` : ''}
                {sel.score > 0 ? ` · score ${sel.score.toFixed(3)}` : ''}
              </span>
              <div className="mono text-sm font-semibold truncate">{sel.id}</div>
            </div>
            {sel.kind === 'entity' && sel.id !== entity && sel.score > 0 && (
              <div className="shrink-0 no-print">
                <Button variant="default"
                        onClick={() => { window.location.hash = `#/case/${encodeURIComponent(sel.id)}`; }}>
                  open case file
                </Button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Time. Only where the run actually recorded it — a run written before
          entity_edges carried timestamps gets no scrubber rather than a dead one. */}
      {timed && (
        <div className="flex items-center gap-3 px-4 py-2 border-t border-rule no-print">
          <Button variant="ghost" onClick={() => setPlaying(!playing)}>
            {playing ? 'pause' : 'replay'}
          </Button>
          <input type="range" min={0} max={births.length - 1} step={1}
                 value={step ?? births.length - 1}
                 aria-label="show flows first seen up to"
                 onChange={(e) => { setPlaying(false); setStep(Number(e.target.value)); }}
                 className="flex-1 accent-[var(--chain)] cursor-pointer" />
          <span className="mono text-2xs text-ink-dim w-48 text-right">
            {cut == null
              ? `all · ${births.length} steps`
              : `${(step ?? 0) + 1}/${births.length} · ${stamp(cut)}`}
          </span>
          <Button variant="ghost" onClick={() => { setPlaying(false); setStep(null); }}>all</Button>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-t border-rule bg-surface-2">
        {swatch('--ink', 'subject')}
        {swatch('--fusion', data ? `alerted ${data.meta.score_lo.toFixed(3)}` : 'alerted (low)')}
        {swatch('--danger', data ? `alerted ${data.meta.score_hi.toFixed(3)}` : 'alerted (high)')}
        {swatch('--ink-dim', 'neighbourhood')}
        {swatch('--network', 'traced path')}
        {sub ? swatch('--chain', 'wallet (address)') : null}
        {sub ? swatch('--data', 'transaction') : null}
        <span className="mono text-2xs text-ink-dim">
          ring = hops · edge width = log value · click a node to trace its path
        </span>
      </div>
    </div>
  );
}
