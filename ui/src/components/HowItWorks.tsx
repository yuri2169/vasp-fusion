/** How it works — the explainer below the landing fold.
 *
 * The hero states the claim. This states the mechanism, because "correlates the
 * network layer with the chain layer" is a sentence anyone can write and nobody
 * can evaluate. Four bands, each answering the next question a sceptical judge
 * asks:
 *
 *   1  why first-seen attribution fails      — the problem the product exists for
 *   2  what makes it different               — each claim beside the figure behind it
 *   3  the two lanes and where they fuse     — an animated flowchart of the real path
 *   4  the nine stages                       — the same copy the wait screen shows
 *   5  what the analyst gets                 — every tool, and where it lives
 *   6  what it measures against a baseline   — numbers, each traceable to an artefact
 *
 * MOTION RULE. The house doctrine forbids fade-up-on-scroll, and nothing here
 * fades up. What scroll does is *arm* the instruments: the lane traces draw
 * themselves, packets start moving, bars grow to their magnitude. Before that
 * point every word is already on screen at full opacity — an explainer that is
 * invisible until scrolled is an explainer that does not exist for a judge who
 * jumps to the bottom.
 *
 * Every figure here is from the bulk profile or from the two real-data
 * validations, read from ui/src/figures.json (scripts/export_figures.py writes it
 * from the pinned artefacts). See docs/ps_compliance.md.
 */
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Bar, Counter, Eyebrow } from '../ui';
import { STAGES, DETAIL, PLAIN, F, millions, thousands, pc } from '../stages';

/** True once the element has been on screen. One-way: the diagram never resets,
 *  because a flowchart that re-draws every time it scrolls past is a fidget toy.
 *
 *  THE TIMER IS NOT OPTIONAL. Armed state gates real content here - an undrawn
 *  lane trace is a flowchart with no arrows in it - and IntersectionObserver
 *  does not run while the document is not being rendered. Measured: in a hidden
 *  browser pane it never fires at all, so the diagram stayed permanently blank.
 *  Same guarantee Counter makes about landing on its final value: the animation
 *  may be missed, the content may not. */
function useArmed<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || armed) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setArmed(true); io.disconnect(); }
    }, { rootMargin: '-12% 0px -12% 0px' });
    io.observe(el);
    const settle = setTimeout(() => setArmed(true), 6000);
    return () => { io.disconnect(); clearTimeout(settle); };
  }, [armed]);
  return [ref, armed] as const;
}

const reduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ------------------------------------------------------------------ diagram */
/* Geometry in one place, and everything in a lane sits on ONE vertical axis:
   the trace, the lane label, the box, and the box's text. Box text used to be
   left-aligned under a centred label, which is what read as misalignment.

   Boxes are filled with --surface and painted over the traces, so a single path
   per lane serves as both the drawn connector and the motion path for its
   packets - the line simply disappears behind each box. */
const VB_W = 1000, VB_H = 528;
const BW = 300, BH = 54;
const LX = 256, RX = 744;                    // lane axes, symmetric about 500
const ROW = [148, 236, 324];                 // lane box centres
const FUSE_Y = 416, FUSE_R = 44;             // the diamond
const SRC_Y = 44, SPLIT_Y = 96;
const OUT_Y = 494;                           // box bottom = 521, inside VB_H. It was 512
                                             // against a 508 viewBox, i.e. clipped.

const NET_PATH = `M500 ${SRC_Y + 22} V${SPLIT_Y} H${LX} V${FUSE_Y} H${500 - FUSE_R}`;
const CHN_PATH = `M500 ${SRC_Y + 22} V${SPLIT_Y} H${RX} V${FUSE_Y} H${500 + FUSE_R}`;
const LANE_LEN = 900;                        // >= either path length, so the offset hides it fully

/* Every node in the diagram, with the plain-language explanation the side card
   shows when you point at it. `id` is the key; `layer` is the semantic colour;
   `sub` is the line printed inside the box itself.

   The card exists because a flowchart box has room for four words and a reader
   who does not already know what "entity × IP co-occurrence" means is not
   helped by four words. Hovering asks the question; the card answers it in the
   register of stages.ts PLAIN. */
type Node = { id: string; layer: 'network' | 'chain' | 'fusion' | 'data';
              head: string; sub: string; title: string; body: string };

const SRC: Node = {
  id: 'src', layer: 'data', head: 'ONE CAPTURE · CSV / JSONL / XML', sub: '',
  title: 'What goes in',
  body: 'One file of captured traffic. Each row is a single transaction as one machine saw ' +
        'it: when it arrived, which IP announced it, and what moved on the chain. CSV, JSONL ' +
        'and XML all read into the same table, and all three are checked to produce identical ' +
        'clean-row counts.',
};
const NET: Node[] = [
  { id: 'n1', layer: 'network', head: 'src IP · port · timestamp',
    sub: 'who relayed it, and exactly when',
    title: 'The half a block explorer does not have',
    body: 'Which machine announced the transaction, from which port, at what moment. A ' +
          'blockchain explorer can tell you money moved; only this side can start to say ' +
          'from where.' },
  { id: 'n2', layer: 'network', head: 'ASN · country · host class',
    sub: 'DB-IP Lite, bundled — nothing leaves the box',
    title: 'Where each machine lives',
    body: 'Every IP is looked up in a database that ships inside the image: which network ' +
          'owns it, which country, and whether it looks like a home line, a VPN or a data ' +
          'centre. That last one matters — it is what decides later whether an attribution ' +
          'can be trusted or has to be thrown away.' },
  { id: 'n3', layer: 'network', head: 'entity × IP co-occurrence',
    sub: 'a sparse matrix, not a first-seen guess',
    title: 'A tally, not a guess',
    body: 'How often each owner was seen from each IP, counted across every announcement. ' +
          'Not "who shouted first" — first-shout is exactly what randomised relay delays ' +
          'scramble. A count over thousands of sightings is not scrambled.' },
];
const CHN: Node[] = [
  { id: 'c1', layer: 'chain', head: 'TXID · addresses · amounts',
    sub: 'inputs, outputs, fee, script type',
    title: 'The blockchain half',
    body: 'The transaction id, the addresses it spent from and paid to, the amounts, the fee ' +
          'and the script type — the public record, exactly as it is written.' },
  { id: 'c2', layer: 'chain', head: 'addresses → actors',
    sub: `common-input ownership: ${(F.bulk_n_addresses / 1e6).toFixed(1)}M → ~${Math.round(F.bulk_n_entities / 1000)}k`,
    title: 'Addresses are not people',
    body: 'If one payment spends from five addresses at once, one person held all five ' +
          `private keys — so those five are one owner. Chain those merges and ${millions(F.bulk_n_addresses)} ` +
          `addresses collapse into roughly ${thousands(F.bulk_n_entities)} owners. A CoinJoin, where ` +
          'many people pay in together on purpose, is left apart. Checked on real Bitcoin: ' +
          `addresses grouped this way share a label ${pc(F.epp_label_agreement)} of the time.` },
  { id: 'c3', layer: 'chain', head: `${F.n_features} features per actor`,
    sub: 'behaviour, timing, network posture, money graph',
    title: `A portrait in ${F.n_features} numbers`,
    body: 'Each owner described by how they spend, what hours they keep, who they deal with, ' +
          'and where they sit in the flow of money. Learned graph embeddings were tested and ' +
          'left out: they helped only on the capture they were fitted to.' },
];
const FUSE: Node = {
  id: 'fuse', layer: 'fusion', head: 'FUSE', sub: '',
  title: 'Where the two halves meet',
  body: 'For every owner–IP pair it asks whether they turn up together more often than their ' +
        'traffic volumes alone would predict — a hypergeometric test, with Benjamini–Hochberg ' +
        'control across all pairs at α 0.01 so that testing millions of pairs does not ' +
        'manufacture findings. It names an IP only for kinds of host where named answers stay ' +
        `under ${pc(F.attribution_target_risk ?? 0.05, 0)} error on held-out data, and never a ` +
        'VPN, Tor or CDN exit. Alongside it, a gradient-boosted model scores how unusual the ' +
        'owner looks and calibrates that into a probability at this capture’s own base rate.',
};
const OUT: Node = {
  id: 'out', layer: 'fusion', head: 'RANKED, EXPLAINABLE LEAD', sub: '',
  title: 'What comes out',
  body: 'One ranked list. Each entry carries a calibrated confidence, the IP behind it where ' +
        'one survived the test, the features that actually drove the score, and the real ' +
        'transaction ids that back it — so an analyst can check the claim rather than take it.',
};
const ALL: Node[] = [SRC, ...NET, ...CHN, FUSE, OUT];

/* Where each node's callout opens, in viewBox units, so the HTML card and the
   SVG leader line agree without either measuring the other.
 *
 * The card always OVERLAPS the diagram, and that is forced, not lazy: two
 * 300-unit lane boxes plus their margins consume the full 1000, so there is no
 * free column to put a 300-unit card in. A popover that covers the far lane for
 * as long as you point at something is the honest trade — and it is why the card
 * is `pointer-events-none`, so it can never steal the hover from the node it is
 * describing or from a node underneath it.
 *
 * `edge` is the node border the leader leaves from; `x` is the card's left edge.
 * Cards are 300 wide and vertically centred on the node, which keeps all seven
 * lane/fuse cards inside the 528-unit box; source and output poke a little into
 * the band's own padding, which is why the callout layer is outside the
 * schematic's horizontal scroller and is not clipped. */
/* `align` is only needed at the two ends. A card centred on the source node
   hangs 39px above the schematic and one centred on the output hangs 42px below
   it — measured — which puts a popover over the band's own heading. Pinning
   those two to the top and bottom edge costs nothing: the leader still leaves
   the node horizontally, it just meets the card nearer a corner than its middle,
   and no code has to measure the card's height to work that out. */
const CARD_W = 300;
const CALLOUT: Record<string, { edge: number; x: number; y: number; align?: 'top' | 'bottom' }> = {
  src:  { edge: 676, x: 700, y: SRC_Y, align: 'top' },
  n1:   { edge: 406, x: 436, y: ROW[0] },
  n2:   { edge: 406, x: 436, y: ROW[1] },
  n3:   { edge: 406, x: 436, y: ROW[2] },
  c1:   { edge: 594, x: 264, y: ROW[0] },
  c2:   { edge: 594, x: 264, y: ROW[1] },
  c3:   { edge: 594, x: 264, y: ROW[2] },
  fuse: { edge: 544, x: 574, y: FUSE_Y },
  out:  { edge: 680, x: 700, y: OUT_Y, align: 'bottom' },
};
/** The leader runs from the node's edge to the card's near edge. */
const leaderTo = (c: { edge: number; x: number }) =>
  c.x > c.edge ? c.x : c.x + CARD_W;

const DEFAULT_CARD = {
  title: 'One capture in, one lead out',
  body: 'Two lanes run the length of this diagram and neither can answer the question alone. ' +
        'The network lane knows which machines were talking; the chain lane knows what was ' +
        'paid. They meet once, at FUSE. Point at any block to see what it does.',
  layer: 'data' as const,
};

/** A lane box. Stroked in its own layer colour rather than carrying a left
 *  accent rule: an accent on the leading edge pulls against centred text, and
 *  the whole box being the layer's colour is the stronger signal anyway.
 *
 *  Hover fills with --active-wash, never with the layer's own wash: the stroke
 *  says which layer this is, the fill says you are pointing at it, and those two
 *  jobs do not get to share a colour. */
function Box({ x, y, node, on, onPoint }: {
  x: number; y: number; node: Node; on: boolean; onPoint: () => void;
}) {
  return (
    <g onMouseEnter={onPoint} onClick={onPoint} style={{ cursor: 'pointer' }}>
      <rect x={x - BW / 2} y={y - BH / 2} width={BW} height={BH}
            fill={on ? 'var(--active-wash)' : 'var(--surface)'}
            stroke={`var(--${node.layer})`} strokeWidth={on ? 2.5 : 1.25} />
      <text x={x} y={y - 4} textAnchor="middle" fill="var(--ink)"
            style={{ font: '600 16px "Public Sans", sans-serif' }}>{node.head}</text>
      {/* --ink-dim on --active-wash measures 4.22:1 in the dark theme. A box
          under the pointer steps its sub-line up. */}
      <text x={x} y={y + 17} textAnchor="middle" fill={on ? 'var(--ink-soft)' : 'var(--ink-dim)'}
            style={{ font: '400 13px "Public Sans", sans-serif' }}>{node.sub}</text>
    </g>
  );
}

function Flow() {
  const [ref, armed] = useArmed<HTMLDivElement>();
  const [at, setAt] = useState<string | null>(null);
  const motion = armed && !reduced();
  const card = ALL.find((n) => n.id === at) ?? DEFAULT_CARD;
  const lane = {
    fill: 'none', strokeWidth: 1.5, strokeDasharray: LANE_LEN,
    strokeDashoffset: armed ? 0 : LANE_LEN,
    style: { transition: 'stroke-dashoffset 1200ms cubic-bezier(.16,1,.3,1)' },
  } as const;
  const hit = (id: string) => ({
    onMouseEnter: () => setAt(id), onClick: () => setAt(id),
    style: { cursor: 'pointer' } as const,
  });

  return (
    <div ref={ref} className="relative" onMouseLeave={() => setAt(null)}>
      <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${VB_W} ${VB_H}`} className="w-full min-w-[680px] h-auto block"
           role="img"
           aria-label={`One capture splits into a network lane and a chain lane. The network
             lane carries source IP, port and timestamp, resolves them to ASN and host class
             offline, and builds an entity by IP co-occurrence matrix. The chain lane carries
             TXIDs, addresses and amounts, collapses addresses into actors by common-input
             ownership, and derives ${F.n_features} features per actor. The two meet at a fusion step —
             a hypergeometric co-occurrence test under Benjamini-Hochberg control, plus a
             calibrated gradient-boosted model — which emits one ranked, explainable lead.`}>
        <defs>
          {(['network', 'chain', 'fusion'] as const).map((l) => (
            <marker key={l} id={`hiw-a-${l}`} viewBox="0 0 8 8" refX="7" refY="4"
                    markerWidth="6" markerHeight="6" orient="auto">
              <path d="M0 0 L8 4 L0 8 z" fill={`var(--${l})`} />
            </marker>
          ))}
        </defs>

        {/* Lane traces, drawn behind everything. Also the packets' motion paths. */}
        <path id="hiw-net" d={NET_PATH} stroke="var(--network)"
              markerEnd="url(#hiw-a-network)" {...lane} />
        <path id="hiw-chn" d={CHN_PATH} stroke="var(--chain)"
              markerEnd="url(#hiw-a-chain)" {...lane} />
        <path d={`M500 ${FUSE_Y + FUSE_R} V${OUT_Y - BH / 2}`} stroke="var(--fusion)"
              strokeWidth={1.5} fill="none" markerEnd="url(#hiw-a-fusion)" />

        {/* Source, and the point where one capture becomes two questions. */}
        <g {...hit('src')}>
          <rect x={500 - 176} y={SRC_Y - 23} width={352} height={46}
                fill={at === 'src' ? 'var(--active-wash)' : 'var(--surface)'}
                stroke="var(--ink)" strokeWidth={at === 'src' ? 2.5 : 1.25} />
          <text x={500} y={SRC_Y + 5} textAnchor="middle" fill="var(--ink)"
                style={{ font: '700 17px Archivo, sans-serif', letterSpacing: '.02em' }}>
            {SRC.head}
          </text>
        </g>
        <circle cx={500} cy={SPLIT_Y} r={3.5} fill="var(--ink)" />

        {/* Lane labels sit ON the axis, in the gap between the split and the
            first box, masked out of the trace by a --paper backing. */}
        {([[LX, 'network layer', 'network'], [RX, 'chain layer', 'chain']] as const).map(
          ([x, label, layer]) => (
            <g key={label}>
              <rect x={x - 74} y={ROW[0] - BH / 2 - 28} width={148} height={22} fill="var(--paper)" />
              <text x={x} y={ROW[0] - BH / 2 - 12} textAnchor="middle" fill={`var(--${layer})`}
                    style={{ font: '600 13px "Public Sans", sans-serif', letterSpacing: '.075em',
                             textTransform: 'uppercase' }}>{label}</text>
            </g>
          ))}

        {NET.map((n, i) => (
          <Box key={n.id} x={LX} y={ROW[i]} node={n} on={at === n.id} onPoint={() => setAt(n.id)} />
        ))}
        {CHN.map((n, i) => (
          <Box key={n.id} x={RX} y={ROW[i]} node={n} on={at === n.id} onPoint={() => setAt(n.id)} />
        ))}

        {/* Fusion. A diamond, not another rectangle: it is a decision, and the one
            place in the diagram where the two colours have to become one. */}
        <g {...hit('fuse')}>
          <path d={`M500 ${FUSE_Y - FUSE_R} L${500 + FUSE_R} ${FUSE_Y} L500 ${FUSE_Y + FUSE_R} L${500 - FUSE_R} ${FUSE_Y} Z`}
                fill={at === 'fuse' ? 'var(--active-wash)' : 'var(--fusion-wash)'}
                stroke="var(--fusion)" strokeWidth={at === 'fuse' ? 2.5 : 1.5} />
          <text x={500} y={FUSE_Y + 6} textAnchor="middle"
                fill={at === 'fuse' ? 'var(--ink)' : 'var(--fusion)'}
                style={{ font: '800 18px Archivo, sans-serif' }}>FUSE</text>
        </g>

        {/* Output */}
        <g {...hit('out')}>
          <rect x={500 - 180} y={OUT_Y - BH / 2} width={360} height={BH}
                fill={at === 'out' ? 'var(--active-wash)' : 'var(--surface)'}
                stroke="var(--ink)" strokeWidth={at === 'out' ? 2.5 : 1.5} />
          <text x={500} y={OUT_Y - 5} textAnchor="middle" fill="var(--ink)"
                style={{ font: '700 17px Archivo, sans-serif', letterSpacing: '.02em' }}>
            {OUT.head}
          </text>
          <text x={500} y={OUT_Y + 17} textAnchor="middle"
                fill={at === 'out' ? 'var(--ink-soft)' : 'var(--ink-dim)'}
                style={{ font: '400 13px "Public Sans", sans-serif' }}>
            confidence · the IP · exact SHAP · the proving TXIDs
          </text>
        </g>

        {/* Packets. SMIL rather than rAF on purpose: it cannot strand a value, it
            costs no JavaScript frame budget, and the browser suspends it with the
            tab. Held back until armed so an off-screen loop never runs.
            pointer-events off, or a packet crossing a box steals its hover. */}
        <g style={{ pointerEvents: 'none' }}>
          {motion && ([['hiw-net', 'network'], ['hiw-chn', 'chain']] as const).flatMap(
            ([href, layer]) => [0, 1, 2].map((i) => (
              <circle key={`${href}${i}`} r={4.5} fill={`var(--${layer})`}>
                {/* NEGATIVE begin, not positive. A positive delay leaves the
                  circle parked at cx/cy — the viewBox origin — as a coloured dot
                  clipped into the top-left corner for up to 3.2s. Measured: six
                  of them sitting at (-4,-4,5,5). A negative offset starts the
                  animation already in progress instead, so the three packets are
                  spread along the lane from the first frame. */}
              <animateMotion dur="3.4s" begin={`-${(i * 3.4) / 3}s`} repeatCount="indefinite">
                  <mpath href={`#${href}`} />
                </animateMotion>
              </circle>
            )))}
          {motion && (
            <circle cx={500} cy={FUSE_Y} r={FUSE_R} fill="none" stroke="var(--fusion)"
                    strokeWidth={1} opacity={0}>
              <animate attributeName="r" values={`${FUSE_R};${FUSE_R + 26}`} dur="1.7s"
                       begin="2.2s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.75;0" dur="1.7s"
                       begin="2.2s" repeatCount="indefinite" />
            </circle>
          )}
        </g>

        {/* The leader: node edge to the card's near edge, at the node's own y.
            Drawn last so it crosses whatever the card is about to cover, and in
            the node's layer colour so the connection is unambiguous when two
            lanes are on screen. */}
        {at && CALLOUT[at] && (() => {
          const c = CALLOUT[at];
          const l = ALL.find((n) => n.id === at)!.layer;
          return (
            <g style={{ pointerEvents: 'none' }}>
              <line x1={c.edge} y1={c.y} x2={leaderTo(c)} y2={c.y}
                    stroke={`var(--${l})`} strokeWidth={1.5} />
              <circle cx={c.edge} cy={c.y} r={3.5} fill={`var(--${l})`} />
            </g>
          );
        })()}
      </svg>
      </div>

      {/* The callout, anchored to the block you are pointing at.
          `pointer-events-none` is load-bearing: the card overlaps the far lane,
          and without it the card would steal the hover from the node underneath
          and the whole thing would flicker. Vertically centred on the node, so
          the leader is a straight horizontal line and nothing has to measure
          anything.

          Hidden below md, where the schematic is narrower than its 680px
          min-width and scrolls horizontally - a card positioned in percentages
          of the container would drift off its own node the moment you scroll.
          That width gets the stacked card underneath instead. */}
      {at && CALLOUT[at] && (() => {
        const c = CALLOUT[at];
        const n = ALL.find((x) => x.id === at)!;
        return (
          <div aria-hidden
               className="hidden md:block absolute z-10 pointer-events-none bg-surface p-3"
               style={{ left: `${(c.x / VB_W) * 100}%`, width: `${(CARD_W / VB_W) * 100}%`,
                        ...(c.align === 'top' ? { top: 0 }
                          : c.align === 'bottom' ? { bottom: 0 }
                          : { top: `${(c.y / VB_H) * 100}%`, transform: 'translateY(-50%)' }),
                        borderTop: `3px solid var(--${n.layer})` }}>
            <div className="colhead" style={{ color: `var(--${n.layer})` }}>
              {n.layer === 'data' ? 'input'
                : n.layer === 'fusion' ? 'model output' : `${n.layer} layer`}
            </div>
            <div className="font-cond font-extrabold uppercase tracking-tight text-ink text-md mt-0.5">
              {n.title}
            </div>
            <p className="text-sm text-ink-soft mt-2">{n.body}</p>
          </div>
        );
      })()}

      {/* Below md the pointer is a finger and the schematic scrolls, so the
          explanation is a plain block underneath rather than an overlay. */}
      <aside aria-hidden className="md:hidden mt-4 bg-surface p-4"
             style={{ borderTop: `3px solid var(--${card.layer})` }}>
        <div className="colhead" style={{ color: `var(--${card.layer})` }}>
          {card.layer === 'data' ? 'the whole picture'
            : card.layer === 'fusion' ? 'model output' : `${card.layer} layer`}
        </div>
        <div className="font-cond font-extrabold uppercase tracking-tight text-ink text-lg mt-1">
          {card.title}
        </div>
        <p className="text-sm text-ink-soft mt-2">{card.body}</p>
        {at === null && (
          <div className="colhead mt-3 text-ink-dim">tap a block</div>
        )}
      </aside>

      {/* The card is pointer-driven, so its text reaches assistive tech here
          instead. Nine terms, no tab stops, nothing a keyboard user has to hunt
          for inside an SVG. */}
      <dl className="sr-only">
        {ALL.map((n) => (
          <div key={n.id}>
            <dt>{n.head} — {n.title}</dt>
            <dd>{n.body}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/* ------------------------------------------------------------------- stages */
/* Which layer each stage works in. This is not decoration and it is not a
   rainbow: it is the same semantic palette the footer key decodes, applied to
   the pipeline, so you can see at a glance that the run crosses from network to
   chain and back before anything is scored. */
const STAGE_LAYER = ['data', 'network', 'chain', 'chain', 'data',
                     'fusion', 'network', 'fusion', 'confirm'] as const;

function Stages() {
  const [i, setI] = useState(0);
  const [held, setHeld] = useState(false);          // any interaction stops the tour
  const [ref, armed] = useArmed<HTMLDivElement>();
  const layer = STAGE_LAYER[i];

  useEffect(() => {
    // Advances itself so the section is doing something when you arrive, and
    // stops the instant you touch it — nothing is worse than a list that moves
    // out from under the thing you were reading.
    if (!armed || held || reduced()) return;
    const t = setInterval(() => setI((n) => (n + 1) % STAGES.length), 6000);
    return () => clearInterval(t);
  }, [armed, held]);

  const pick = (n: number) => { setI(n); setHeld(true); };

  return (
    <div ref={ref} className="grid gap-px bg-rule lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
      <ol className="bg-surface">
        {STAGES.map(([name, what], n) => {
          const on = n === i;
          const l = STAGE_LAYER[n];
          return (
            <li key={name}>
              <button onClick={() => pick(n)} onMouseEnter={() => pick(n)}
                      aria-current={on ? 'step' : undefined}
                      className={`w-full text-left flex items-center gap-3 px-3 py-2
                                  cursor-pointer transition-colors duration-150
                                  ${on ? 'bg-active-wash' : 'hover:bg-surface-2'}`}
                      style={on ? { boxShadow: `inset 3px 0 0 0 var(--${l})` } : undefined}>
                {/* The layer chip is the colour. Every row carries one, so the
                    column reads as a sequence of layers before it reads as text. */}
                <span aria-hidden className="w-1.5 h-6 shrink-0"
                      style={{ background: `var(--${l})`, opacity: on ? 1 : 0.45 }} />
                <span className={`mono text-2xs w-4 shrink-0 ${on ? 'text-ink' : 'text-ink-dim'}`}>
                  {n + 1}
                </span>
                <span className="min-w-0">
                  <span className={`block font-cond font-bold uppercase tracking-tight text-sm
                                    ${on ? 'text-ink' : 'text-ink-soft'}`}>{name}</span>
                  {/* --ink-dim on --active-wash measures 4.22:1 in the dark
                      theme, under the 4.5 floor. The selected row steps up. */}
                  <span className={`block text-2xs ${on ? 'text-ink-soft' : 'text-ink-dim'}`}>
                    {what}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      {/* No self-start: the panel stretches to the list, and carries both
          registers of the same explanation so the column is not half empty. */}
      <div className="bg-surface flex flex-col p-4 sm:p-6"
           style={{ borderTop: `3px solid var(--${layer})` }}>
        <div className="flex items-baseline gap-3">
          <span className="figure" style={{ fontSize: 34, color: `var(--${layer})` }}>
            {String(i + 1).padStart(2, '0')}
          </span>
          <span className="font-cond font-extrabold uppercase tracking-tight text-ink text-lg">
            {DETAIL[i][0]}
          </span>
          <span className="colhead ml-auto shrink-0" style={{ color: `var(--${layer})` }}>
            {layer === 'data' ? 'neutral' : layer === 'confirm' ? 'provenance' : `${layer} layer`}
          </span>
        </div>

        {/* Plain first. Someone who bounces after one sentence should still have
            got the right sentence. */}
        <p className="text-lg text-ink mt-3 max-w-[58ch]" style={{ lineHeight: 1.45 }}>
          {PLAIN[i]}
        </p>

        <div className="mt-4 pt-3 border-t border-rule-soft">
          <div className="colhead mb-1">how, exactly</div>
          <p className="text-md text-ink-soft max-w-[68ch]">{DETAIL[i][1]}</p>
        </div>

        {/* A nine-segment rail: where you are, and the layer sequence in one
            line. It fills the bottom of the panel with information rather than
            with padding. */}
        <div className="mt-auto pt-6">
          <div className="flex gap-px" aria-hidden>
            {STAGES.map(([name], n) => (
              <span key={name} className="h-1.5 flex-1 transition-opacity duration-200"
                    style={{ background: `var(--${STAGE_LAYER[n]})`, opacity: n === i ? 1 : 0.25 }} />
            ))}
          </div>
          <div className="colhead mt-2 flex items-baseline gap-2">
            <span>stage <span className="mono text-ink-dim">{i + 1}</span> of
              <span className="mono text-ink-dim"> {STAGES.length}</span></span>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ results */
/* value / baseline pairs. `note` says what the baseline IS, because a number
   without its comparison is a claim, and this project reports the all-negative
   baseline next to accuracy for exactly that reason. */
const RESULTS: {
  label: string; value: number; base: number; dp: number;
  ours: string; theirs: string; note: string; layer: 'fusion' | 'chain' | 'network';
}[] = [
  { label: 'detection · PR-AUC', value: F.detection_pr_auc, base: F.bulk_base_rate, dp: 4, layer: 'fusion',
    ours: 'model', theirs: 'base rate',
    note: `${Math.round(F.detection_pr_auc / F.bulk_base_rate)}× the ${pc(F.bulk_base_rate)} base rate on ` +
          `${(F.bulk_rows / 1e6).toFixed(2)}M rows. Rules alone score ${F.rules_only_pr_auc.toFixed(4)}` +
          `${F.rules_only_pr_auc < F.bulk_base_rate ? ' — below it.' : '.'}` },
  { label: 'attribution · top-1 when it answers', value: F.attribution_top1_answered, base: F.attribution_chance,
    dp: 4, layer: 'network', ours: 'measured', theirs: 'chance',
    note: `Counting every refusal as a miss: ${F.attribution_top1_all_gradable}. It declined ` +
          `${F.attribution_declined.toLocaleString()} actors rather than guess — VPN, Tor and CDN exits are never named.` },
  { label: 'clustering · label agreement', value: F.epp_label_agreement, base: F.epp_shuffle_control, dp: 4,
    layer: 'chain', ours: 'real Bitcoin', theirs: 'shuffle control',
    note: `Not synthetic. ${F.epp_n_test_addresses.toLocaleString()} Elliptic++ addresses, address-disjoint split.` },
  { label: 'chain detector on Elliptic · F1', value: F.elliptic_f1, base: F.elliptic_published_f1, dp: 4,
    layer: 'chain', ours: 'ours', theirs: 'Weber et al.',
    note: `${F.elliptic_n_labelled.toLocaleString()} real labelled transactions, matching the published temporal split.` },
];

function Results() {
  const [ref, armed] = useArmed<HTMLDivElement>();
  return (
    <div ref={ref} className="grid gap-px bg-rule sm:grid-cols-2">
      {RESULTS.map((r, n) => {
        const max = Math.max(r.value, r.base);
        return (
          <div key={r.label} className="bg-surface p-4">
            <div className="colhead mb-2">{r.label}</div>
            <div className="flex items-baseline gap-2">
              <span className="figure" style={{ fontSize: 32, color: `var(--${r.layer})` }}>
                {armed ? <Counter value={r.value} decimals={r.dp} duration={800} /> : r.value.toFixed(r.dp)}
              </span>
              <span className="text-2xs text-ink-dim">{r.ours}</span>
            </div>
            {/* Not gated on `armed`: the baseline is the point of the figure, and
                a number without its comparison is a claim. The growth is the
                animation; the bar itself is content. */}
            <div className="mt-2 space-y-1">
              <Bar value={r.value} max={max} layer={r.layer} width="100%" height={7} delay={n * 60} />
              <Bar value={r.base} max={max} layer="data" width="100%" height={7} delay={n * 60 + 90} />
            </div>
            <div className="text-2xs text-ink-dim mt-1">
              <span className="mono">{r.base.toFixed(r.dp)}</span> {r.theirs}
            </div>
            <p className="text-2xs text-ink-soft mt-2 max-w-[46ch]">{r.note}</p>
          </div>
        );
      })}
    </div>
  );
}


/* ------------------------------------------------------------- innovations */
/* What this does that a block explorer or a first-relay tool does not. Each
   claim sits beside the measured figure that carries it, so a judge can check
   the number instead of taking the sentence. No comparison with anyone else's
   system is made here: we have not run theirs. */
type Layer = 'network' | 'chain' | 'fusion' | 'confirm' | 'danger' | 'data';
const INNOVATIONS: { layer: Layer; title: string; body: string; proof: ReactNode }[] = [
  { layer: 'network', title: 'Network ⇄ chain attribution',
    body: 'Given an owner on the chain, which machine is behind it — decided by a significance ' +
          'test across every sighting, not by whoever relayed the transaction first.',
    proof: <><b>{pc(F.attribution_top1_answered, 1)}</b> right when it answers · {pc(F.attribution_chance, 1)} by chance</> },
  { layer: 'network', title: 'It declines rather than guesses',
    body: 'An IP is named only where named answers stayed under ' +
          `${pc(F.attribution_target_risk ?? 0.05, 0)} error on held-out data, and never a VPN, Tor or ` +
          'CDN exit. Every refusal is counted and shown, not hidden.',
    proof: <><b>{F.attribution_declined.toLocaleString()}</b> actors declined · {pc(F.attribution_error_among_answered ?? 0, 2)} error among answers</> },
  { layer: 'chain', title: 'It tests its own data for shortcuts',
    body: 'A leak test trains only on fields with no path to the label. If they score well above ' +
          'the base rate, the synthetic data is leaking the answer and the build fails.',
    proof: <><b>{F.leak_lift.toFixed(2)}×</b> base rate for those fields · {F.leak_control_lift.toFixed(2)}× for the full model · gate {F.leak_gate.toFixed(2)}×</> },
  { layer: 'fusion', title: 'Probabilities, with honest ranges',
    body: 'Scores are calibrated to the capture’s own base rate and shown as a range kept inside ' +
          '0–1, next to the features that drove them in plain English.',
    proof: <>calibration error <b>{F.ece_shown}</b> · {F.ece_before_prior_shift} before the base-rate correction</> },
  { layer: 'chain', title: 'Checked on real Bitcoin',
    body: 'The chain half is validated on real labelled transactions and addresses, not only on ' +
          'data we generated ourselves.',
    proof: <>Elliptic F1 <b>{F.elliptic_f1}</b> vs {F.elliptic_published_f1} published · clusters share a label {pc(F.epp_label_agreement, 1)}</> },
  { layer: 'confirm', title: 'Offline and reproducible',
    body: 'One process, no network, GeoIP and world map bundled. Every run records its input’s ' +
          'SHA-256, seed, feature version and commit, and make reproduce regenerates every figure.',
    proof: <><b>{millions(F.bulk_rows, 2)}</b> rows scored on one laptop, no cloud</> },
];

function Innovations() {
  return (
    <div className="grid gap-px bg-rule md:grid-cols-2 lg:grid-cols-3">
      {INNOVATIONS.map((x, n) => (
        <div key={x.title} className="bg-surface p-4 sm:p-5 flex flex-col"
             style={{ borderTop: `3px solid var(--${x.layer})` }}>
          <div className="flex items-baseline gap-3">
            <span className="figure" style={{ fontSize: 28, color: `var(--${x.layer})` }}>
              {String(n + 1).padStart(2, '0')}
            </span>
            <span className="font-cond font-extrabold uppercase tracking-tight text-ink text-md">
              {x.title}
            </span>
          </div>
          <p className="text-sm text-ink-soft mt-2 max-w-[52ch]">{x.body}</p>
          <div className="mt-auto pt-3">
            <div className="mono text-2xs text-ink-soft pt-2 border-t border-rule-soft
                            [&_b]:font-semibold [&_b]:text-ink">
              {x.proof}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------- toolkit */
/* Every tool the analyst gets, and where it lives. The glyphs draw themselves
   once the band is on screen - an instrument coming alive, never a fade-up -
   and are simply there under reduced motion. */
const TOOLS: { layer: Layer; title: string; body: string; where: string; icon: ReactNode }[] = [
  { layer: 'fusion', title: 'Ranked lead queue', where: 'Alerts',
    body: 'Every lead ranked by the model, with its probability range, pattern and evidence. A ' +
          'table to compare, a dossier to read, a focus view to present.',
    icon: (<><path pathLength={1} d="M3 5h14" /><path pathLength={1} d="M3 10h10" /><path pathLength={1} d="M3 15h6" /></>) },
  { layer: 'fusion', title: 'Case file, to PDF', where: 'Alerts → open a lead → PDF',
    body: 'Plain-English assessment, the features behind the score, the evidence chain with real ' +
          'TXIDs, and what would change the confidence. One click prints it.',
    icon: (<><path pathLength={1} d="M5 2h7l4 4v12H5z" /><path pathLength={1} d="M12 2v4h4" /><path pathLength={1} d="M8 10h6" /><path pathLength={1} d="M8 13.5h6" /></>) },
  { layer: 'chain', title: 'Operations, not wallets', where: 'Case file → members',
    body: 'Flagged actors that paid each other are one case (CASE-001…), with the money that moved ' +
          'between members — one row per operation, not one per wallet.',
    icon: (<><circle pathLength={1} cx="5" cy="14" r="2.2" /><circle pathLength={1} cx="15" cy="14" r="2.2" /><circle pathLength={1} cx="10" cy="5" r="2.2" /><path pathLength={1} d="M6.4 12.2 8.8 6.9M11.2 6.9l2.4 5.3M7.2 14h5.6" /></>) },
  { layer: 'danger', title: 'Watchlist', where: 'Watchlist',
    body: 'Upload known-bad wallets and follow the money one to three payment hops, with the path. ' +
          'Kept apart from the model: nearness is a reason to look, not a score.',
    icon: (<><circle pathLength={1} cx="10" cy="10" r="7" /><circle pathLength={1} cx="10" cy="10" r="3.5" /><path pathLength={1} d="M10 1v3M10 16v3M1 10h3M16 10h3" /></>) },
  { layer: 'network', title: 'Offline map', where: 'Map',
    body: 'Where leads announce from, drawn from bundled data with no tiles. Exits are marked as ' +
          'exits, and a replay adds each lead at its first transaction.',
    icon: (<><circle pathLength={1} cx="10" cy="10" r="7.5" /><path pathLength={1} d="M2.5 10h15" /><path pathLength={1} d="M10 2.5c2.6 2.4 2.6 12.6 0 15M10 2.5c-2.6 2.4-2.6 12.6 0 15" /></>) },
  { layer: 'chain', title: 'Link graph, exportable', where: 'Case file → link analysis',
    body: 'The payment neighbourhood of a lead, replayable in time and downloadable as GraphML for ' +
          'Gephi, Maltego or i2, or as a CSV edge list with its IPs.',
    icon: (<><circle pathLength={1} cx="4" cy="5" r="2" /><circle pathLength={1} cx="16" cy="5" r="2" /><circle pathLength={1} cx="10" cy="15" r="2" /><path pathLength={1} d="M5.8 5h8.4M5 6.8l4 6.4M15 6.8l-4 6.4" /></>) },
  { layer: 'confirm', title: 'Triage, on the record', where: 'Alerts → verdict',
    body: 'Confirm or dismiss with a reason and the analyst’s name. The next run re-ranks on it; ' +
          'the model is never retrained on clicks.',
    icon: (<><path pathLength={1} d="M3 10.5 7.5 15 17 5" /></>) },
  { layer: 'confirm', title: 'Provenance', where: 'Provenance',
    body: 'Input hash, seed, feature version, commit and stage timings for every run, so any ' +
          'figure can be traced back and regenerated.',
    icon: (<><path pathLength={1} d="M7 3 5.5 17M14.5 3 13 17M3 7.5h14M2.5 12.5h14" /></>) },
  { layer: 'data', title: 'Hardened by default', where: 'Every upload',
    body: 'Uploads are stored under server-chosen names, writes from other websites are refused, ' +
          'and the API scores only its own data folder.',
    icon: (<><path pathLength={1} d="M10 2 3.5 4.5v5c0 4.2 2.8 6.8 6.5 8.5 3.7-1.7 6.5-4.3 6.5-8.5v-5z" /><path pathLength={1} d="m7 10 2.2 2.2L13.5 8" /></>) },
];

function Toolkit() {
  const [ref, armed] = useArmed<HTMLDivElement>();
  return (
    <div ref={ref} className="grid gap-px bg-rule sm:grid-cols-2 lg:grid-cols-3">
      {TOOLS.map((t) => (
        <div key={t.title} className="bg-surface p-4 sm:p-5 flex flex-col">
          <div className="flex items-center gap-3">
            <span className="w-9 h-9 shrink-0 grid place-items-center"
                  style={{ color: `var(--${t.layer})`,
                           background: t.layer === 'data' ? 'var(--surface-2)' : `var(--${t.layer}-wash)` }}>
              <svg viewBox="0 0 20 20" width={20} height={20} fill="none" stroke="currentColor"
                   strokeWidth={1.5} strokeLinecap="square" aria-hidden
                   className={armed ? 'hiw-glyph' : 'hiw-glyph-idle'}>{t.icon}</svg>
            </span>
            <span className="font-cond font-extrabold uppercase tracking-tight text-ink text-md">
              {t.title}
            </span>
          </div>
          <p className="text-sm text-ink-soft mt-3 max-w-[52ch]">{t.body}</p>
          <div className="mt-auto pt-3 text-2xs text-ink-dim">
            in the app · <span className="text-ink-soft">{t.where}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

/* -------------------------------------------------------------------- shell */
export function HowItWorks() {
  return (
    /* GROUND. Four opaque plates on a live field, not one flat slab.
     *
     * The ground here is transparent at 55%, so the diffusion field behind the
     * whole landing shows through the gaps BETWEEN the bands - the page breathes
     * and the background is the product's own problem still running underneath.
     *
     * TEXT NEVER SITS ON THE GROUND, and that is measured, not fussiness.
     * Letting the field through under body text costs ~0.6 of a contrast point
     * in the light theme: --fusion 4.71 -> 4.11 and --ink-dim 4.95 -> 4.32,
     * both under the AA floor. The graph-paper grid is no better — solving for
     * the strongest grid line that still clears 4.55:1 against --chain gives an
     * alpha of 0.075, a ground shift of 1.02:1, i.e. a grid nobody can see.
     * --chain and --fusion have about 4% of headroom on paper and there is
     * nothing to spend it on.
     *
     * So the ground carries the texture and the plates carry the words. */
    <div id="how" className="relative plate-grid scroll-mt-12"
         style={{ backgroundColor: 'color-mix(in srgb, var(--paper) 55%, transparent)' }}>
      <div className="mx-auto max-w-[78rem] px-4 sm:px-8 lg:px-12 py-12 sm:py-12 space-y-8">

        {/* ---- 1 · the problem ---- */}
        <section className="bg-paper border border-rule px-6 sm:px-8 lg:px-12 py-8 sm:py-12">
          <Eyebrow>the problem</Eyebrow>
          <h2 className="display text-ink mt-2" style={{ fontSize: 'clamp(24px,3.4vw,40px)' }}>
            The first peer to shout<br />is not the peer who paid
          </h2>
          <div className="grid gap-6 mt-6 md:grid-cols-3">
            <p className="text-md text-ink-soft md:col-span-2 max-w-[62ch]">
              Bitcoin Core relays every announcement after a{' '}
              <span className="text-network font-semibold">randomised per-peer delay</span>, so arrival
              order is close to noise. A tool that trusts the first sighting names the wrong node.
            </p>
            <p className="text-md text-ink-soft max-w-[46ch]">
              This tests, across <span className="text-ink">every</span> announcement, whether an
              actor and an IP co-occur more than chance. On shared infrastructure it{' '}
              <span className="text-ink font-semibold">suppresses the attribution</span>.
            </p>
          </div>
        </section>

        {/* ---- 2 · what makes it different ---- */}
        <section className="bg-paper border border-rule px-6 sm:px-8 lg:px-12 py-8 sm:py-12">
          <Eyebrow right="each claim beside the figure behind it">what makes it different</Eyebrow>
          <h2 className="display text-ink mt-2" style={{ fontSize: 'clamp(22px,3vw,34px)' }}>
            Six things that set it apart
          </h2>
          <p className="text-sm text-ink-soft mt-2 mb-6 max-w-[70ch]">
            Figures 01–04 come from the <span className="text-ink">synthetic</span> bulk capture
            ({millions(F.bulk_rows, 2)} rows, {pc(F.bulk_base_rate)} base rate); 05 is real Bitcoin.
            The network half has not yet been tested on live nodes.
          </p>
          <Innovations />
        </section>

        {/* ---- 3 · the flowchart ---- */}
        <section className="bg-paper border border-rule px-6 sm:px-8 lg:px-12 py-8 sm:py-12">
          <Eyebrow right="hover any block for what it does">how the two layers meet</Eyebrow>
          <div className="mt-3">
            <Flow />
          </div>
        </section>

        {/* ---- 4 · the stages ---- */}
        <section className="bg-paper border border-rule px-6 sm:px-8 lg:px-12 py-8 sm:py-12">
          <Eyebrow>nine stages, on this machine, with no network</Eyebrow>
          <div className="mt-4"><Stages /></div>
        </section>

        {/* ---- 5 · what the analyst gets ---- */}
        <section className="bg-paper border border-rule px-6 sm:px-8 lg:px-12 py-8 sm:py-12">
          <Eyebrow right="all offline, in one app">what the analyst gets</Eyebrow>
          <div className="mt-4"><Toolkit /></div>
        </section>

        {/* ---- 6 · results ---- */}
        <section className="bg-paper border border-rule px-6 sm:px-8 lg:px-12 py-8 sm:py-12">
          <Eyebrow>measured, not claimed</Eyebrow>
          <p className="text-md text-ink-soft mt-2 mb-4 max-w-[64ch]">
            From <span className="mono text-ink">make reproduce</span> on the synthetic bulk capture
            ({millions(F.bulk_rows, 2)} rows, {pc(F.bulk_base_rate)} base rate) and on{' '}
            <span className="text-ink">real labelled Bitcoin</span>, each beside its baseline.
          </p>
          <Results />
        </section>

      </div>
    </div>
  );
}
