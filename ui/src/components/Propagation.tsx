/** The live diffusion field behind the landing screen.
 *
 * NOT a particle background. This is the product's own problem, drawn: a peer
 * announces a transaction and the rest relay it after a RANDOMISED per-peer
 * delay - the defence Bitcoin Core added to defeat first-relay inference (Koshy
 * FC'14, Biryukov CCS'14). Arrival order therefore tells you almost nothing
 * about who sent it, which is why this system runs a significance test over many
 * announcements instead of trusting the first sighting.
 *
 * THE POINTER IS A VANTAGE POINT. Move it and you are a listening node: the
 * peers inside your observation radius light up and report to you. Move away and
 * they go dark. That is the sensitivity curve on the Model page made tangible -
 * attribution accuracy is a function of how much of the network you can see, and
 * it inverts below ~10% coverage.
 *
 * Implementation notes that matter:
 *  - Everything is time-based (dt), never per-frame decay. Frame-based easing
 *    runs at a different speed on a 120Hz display than on a 60Hz one, which is
 *    the usual reason a canvas animation feels janky on someone else's machine.
 *  - Three overlapping waves, staggered, so the field is never empty and never
 *    pulses in unison.
 *  - Colours are re-read from the CSS tokens every frame, so the field follows
 *    the theme with no extra wiring.
 */
import { useEffect, useRef } from 'react';

type Node = { x: number; y: number; hx: number; hy: number; phase: number; lit: number; seen: number };
type Edge = { a: number; b: number };
type Pulse = { e: number; dir: 1 | -1; t: number; dur: number; wave: number };
type Wave = { origin: number; born: number; ring: number };

const DENSITY = 6200;         // one node per N px² - keeps density constant at any size
const MAX_NODES = 200;        // full-bleed needs a real mesh; 49 nodes read as dust
const VANTAGE_R = 230;        // reach of the pointer's influence, in px - a falloff, not an edge
/* The wave runs faster over the landing than behind the explainer. One canvas is
   fixed behind the whole page, so the speed has to follow the scroll instead:
   the hero wants a field with some life in it, the explainer wants it calm
   behind text people are actually reading. */
const WAVE_HERO = 1.9;        // multiplier at the top of the page
const WAVE_CALM = 1.0;        // multiplier once the explainer fills the screen

export function Propagation({ className = '' }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const ctx = cv.getContext('2d', { alpha: true }); if (!ctx) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let raf = 0, w = 0, h = 0, last = 0;
    /* ACCUMULATED wave time, not `now`. The speed changes as the page scrolls,
       and sin(now / T) with a changing T makes the phase jump the instant T
       moves - the whole field would snap. Integrating dt * speed keeps the phase
       continuous however the speed varies. */
    let waveT = 0;
    let nodes: Node[] = [], edges: Edge[] = [], adj: number[][] = [];
    let pulses: Pulse[] = [], waves: Wave[] = [];
    let seenBy: Set<number>[] = [];
    const rand = mulberry(20260826);
    const ptr = { x: -9999, y: -9999, on: 0 };   // `on` eases 0..1 so it never snaps

    function layout() {
      const r = cv!.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = r.width; h = r.height;
      if (!w || !h) return;
      cv!.width = Math.round(w * dpr); cv!.height = Math.round(h * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);

      const target = Math.min(MAX_NODES, Math.max(36, Math.round((w * h) / DENSITY)));
      const cols = Math.max(4, Math.round(Math.sqrt(target * (w / h))));
      const rows = Math.max(3, Math.ceil(target / cols));
      nodes = [];
      for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) {
        if (nodes.length >= target) break;
        const x = ((j + 0.5) / cols) * w + (rand() - 0.5) * (w / cols) * 0.8;
        const y = ((i + 0.5) / rows) * h + (rand() - 0.5) * (h / rows) * 0.8;
        nodes.push({ x, y, hx: x, hy: y, phase: rand() * Math.PI * 2, lit: 0, seen: 0 });
      }
      edges = []; adj = nodes.map(() => []);
      nodes.forEach((n, i) => {
        nodes.map((m, k) => ({ k, d: (m.x - n.x) ** 2 + (m.y - n.y) ** 2 }))
          .filter((o) => o.k !== i).sort((a, b) => a.d - b.d).slice(0, 4)
          .forEach((o) => {
            if (edges.some((e) => (e.a === i && e.b === o.k) || (e.a === o.k && e.b === i))) return;
            const id = edges.length;
            edges.push({ a: i, b: o.k });
            adj[i].push(id); adj[o.k].push(id);
          });
      });
      pulses = []; waves = []; seenBy = [];
    }

    function announce(now: number) {
      const wave = waves.length;
      const origin = Math.floor(rand() * nodes.length);
      waves.push({ origin, born: now, ring: 0 });
      seenBy[wave] = new Set([origin]);
      nodes[origin].lit = 1;
      emit(origin, wave);
    }

    function emit(from: number, wave: number) {
      adj[from].forEach((eid) => {
        const e = edges[eid];
        const to = e.a === from ? e.b : e.a;
        if (seenBy[wave].has(to)) return;
        seenBy[wave].add(to);
        // The delay is RANDOM per peer, not proportional to distance. That is
        // the whole point - nothing about the order of arrival names the origin.
        const dur = 520 + rand() * 1500;
        pulses.push({ e: eid, dir: e.a === from ? 1 : -1, t: -rand() * 240, dur, wave });
      });
    }

    function step(now: number, dt: number) {
      // On first mount the canvas can measure 0x0 for a frame, so layout() bails
      // and leaves the arrays empty - while the rAF loop has already started and
      // would index nodes[0] of nothing. Guard here rather than in five places.
      if (!nodes.length) return;
      // Keep three waves in flight, staggered, so the field never goes quiet
      // and never beats in unison.
      if (waves.length < 4 || now - waves[waves.length - 1].born > 1700) {
        if (waves.length < 4 || pulses.length < 14) announce(now);
      }
      if (waves.length > 8) { waves.splice(0, waves.length - 8); seenBy.splice(0, seenBy.length - 8); }

      pulses = pulses.filter((p) => {
        p.t += dt;
        if (p.t < p.dur) return true;
        const e = edges[p.e];
        const to = p.dir === 1 ? e.b : e.a;
        nodes[to].lit = 1;
        if (seenBy[p.wave]) emit(to, p.wave);
        return false;
      });

      // Speed eases from WAVE_HERO to WAVE_CALM across the first screenful, so
      // the field settles as the explainer takes over rather than switching.
      const k = Math.min(1, window.scrollY / Math.max(1, window.innerHeight * 0.85));
      waveT += dt * (WAVE_HERO + (WAVE_CALM - WAVE_HERO) * k);

      const decay = Math.pow(0.5, dt / 1400);      // time-based half-life, not per-frame
      nodes.forEach((n, i) => {
        n.lit *= decay;
        /* A TRAVELLING WAVE, not per-node shimmer.
         *
         * The phase used to be `n.phase` alone — a random constant per node — so
         * every node bobbed on its own schedule and the field read as static
         * noise that happened to jitter. Subtracting a term derived from the
         * node's own POSITION makes the phase advance across space as well as
         * time, so the whole mesh rolls in one direction: a wave crossing the
         * page rather than two hundred independent wobbles.
         *
         * Two periods that do not divide (2600 / 3300) keep the crests from
         * relanding in the same place, and a fifth-weight of the old random
         * phase keeps it organic rather than mechanical. Still time-based, so it
         * runs at the same speed on a 60Hz and a 120Hz display.
         *
         * AMPLITUDE AND WAVELENGTH ARE BOTH TUNED TO BE SEEN. Mean node spacing
         * is sqrt(DENSITY) = 79px, so a 7px sway was 9% of the gap - present in
         * the numbers, invisible on screen. 20px is a quarter of the spacing and
         * unmistakable. A coherent wave tolerates that where random jitter would
         * not: neighbours move almost together, so the mesh sways instead of
         * tangling. The 190 divisor puts a little over one full crest across a
         * 1400px screen; at 300 barely half a wave fitted and the whole field
         * looked like it was sliding rather than rolling.
         *
         * Edges and dots need nothing of their own - both draw from n.x/n.y, and
         * so do the pulses and the ripples - so the whole mesh waves together. */
        const wx = (n.hx * 0.85 + n.hy * 0.52) / 190;
        n.x = n.hx + Math.sin(waveT / 2600 - wx + n.phase * 0.2) * 20;
        n.y = n.hy + Math.cos(waveT / 3300 - wx * 0.92 + n.phase * 0.2) * 16;
        const d = Math.hypot(n.x - ptr.x, n.y - ptr.y);
        const k = Math.max(0, 1 - d / VANTAGE_R);
        const want = ptr.on * k * k * (3 - 2 * k);   // smoothstep: no hard rim
        n.seen += (want - n.seen) * Math.min(1, dt / 90);   // eased, never snapping
        void i;
      });
    }

    function draw(now: number) {
      if (!nodes.length) return;
      const cs = getComputedStyle(document.documentElement);
      const tok = (n: string, f: string) => cs.getPropertyValue(n).trim() || f;
      const rule = tok('--rule', '#C3CCD4');
      const chain = tok('--chain', '#2D6A9F');
      const network = tok('--network', '#7B4B94');
      const fusion = tok('--fusion', '#8C5B0E');
      const dim = tok('--ink-dim', '#56646F');

      ctx!.clearRect(0, 0, w, h);
      ctx!.lineCap = 'round';

      // --- edges -----------------------------------------------------------
      edges.forEach((e) => {
        const A = nodes[e.a], B = nodes[e.b];
        const obs = Math.max(A.seen, B.seen);
        ctx!.beginPath(); ctx!.moveTo(A.x, A.y); ctx!.lineTo(B.x, B.y);
        ctx!.strokeStyle = obs > 0.02 ? chain : rule;
        ctx!.lineWidth = 1;
        ctx!.globalAlpha = 0.42 + obs * 0.5;
        ctx!.stroke();
      });

      // --- travelling announcements ---------------------------------------
      // A dot moving along the wire reads as a message in transit. A fading
      // line just reads as a line fading.
      pulses.forEach((p) => {
        if (p.t < 0) return;
        const e = edges[p.e];
        const A = p.dir === 1 ? nodes[e.a] : nodes[e.b];
        const B = p.dir === 1 ? nodes[e.b] : nodes[e.a];
        const k = easeOut(Math.min(1, p.t / p.dur));
        const x = A.x + (B.x - A.x) * k, y = A.y + (B.y - A.y) * k;
        const tail = Math.max(0, k - 0.22);
        ctx!.beginPath();
        ctx!.moveTo(A.x + (B.x - A.x) * tail, A.y + (B.y - A.y) * tail);
        ctx!.lineTo(x, y);
        ctx!.strokeStyle = chain; ctx!.lineWidth = 1.7;
        ctx!.globalAlpha = 0.85 * (1 - Math.abs(k - 0.5) * 0.5);
        ctx!.stroke();
        ctx!.beginPath(); ctx!.arc(x, y, 1.9, 0, Math.PI * 2);
        ctx!.fillStyle = chain; ctx!.globalAlpha = 0.95; ctx!.fill();
      });

      // --- nodes -----------------------------------------------------------
      nodes.forEach((n) => {
        const s = 2.6 + n.lit * 2.4 + n.seen * 1.6;
        ctx!.beginPath(); ctx!.rect(n.x - s / 2, n.y - s / 2, s, s);
        ctx!.fillStyle = n.seen > 0.03 ? chain : n.lit > 0.03 ? fusion : dim;
        ctx!.globalAlpha = 0.5 + n.lit * 0.45 + n.seen * 0.45;
        ctx!.fill();
        if (n.seen > 0.05) {
          // What this vantage point can hear.
          ctx!.beginPath(); ctx!.moveTo(n.x, n.y); ctx!.lineTo(ptr.x, ptr.y);
          ctx!.strokeStyle = chain; ctx!.lineWidth = 0.9;
          ctx!.globalAlpha = n.seen * 0.55; ctx!.stroke();
        }
      });

      // --- wave origins ----------------------------------------------------
      waves.forEach((wv) => {
        const n = nodes[wv.origin]; if (!n) return;
        const age = (now - wv.born) / 2600;
        if (age > 1.6) return;
        ctx!.beginPath(); ctx!.arc(n.x, n.y, 6 + age * 46, 0, Math.PI * 2);
        ctx!.strokeStyle = network; ctx!.lineWidth = 1.2;
        ctx!.globalAlpha = Math.max(0, 0.5 - age * 0.34); ctx!.stroke();
        ctx!.beginPath(); ctx!.arc(n.x, n.y, 3.6, 0, Math.PI * 2);
        ctx!.fillStyle = network; ctx!.globalAlpha = 0.95; ctx!.fill();
      });

      // --- the vantage point ------------------------------------------------
      // Deliberately the most vivid thing on the screen while the pointer is in
      // the field: it is the only part of this page the visitor controls, and
      // what it demonstrates - coverage determines what you can attribute - is
      // the argument the Model page makes with a curve.
      if (ptr.on > 0.01) {
        const g = ctx!.createRadialGradient(ptr.x, ptr.y, 0, ptr.x, ptr.y, VANTAGE_R);
        g.addColorStop(0, withAlpha(chain, 0.17 * ptr.on));
        g.addColorStop(0.4, withAlpha(chain, 0.075 * ptr.on));
        g.addColorStop(0.72, withAlpha(chain, 0.018 * ptr.on));
        g.addColorStop(1, withAlpha(chain, 0));
        ctx!.globalAlpha = 1; ctx!.fillStyle = g;
        ctx!.beginPath(); ctx!.arc(ptr.x, ptr.y, VANTAGE_R, 0, Math.PI * 2); ctx!.fill();

        // NO drawn boundary. A dashed ring states a hard edge the effect does not
        // actually have - what a vantage point hears falls away with distance, it
        // does not stop at a line. The gradient above and the per-node falloff
        // are the whole story; drawing a circle on top only contradicted them.
        ctx!.beginPath(); ctx!.arc(ptr.x, ptr.y, 3.4, 0, Math.PI * 2);
        ctx!.fillStyle = chain; ctx!.globalAlpha = ptr.on * 0.9; ctx!.fill();
      }
      ctx!.globalAlpha = 1;
    }

    layout();
    if (reduced) {
      // Still shows the network and one propagation, just without motion.
      announce(0);
      for (let i = 0; i < 900; i++) step(i * 30, 30);
      nodes.forEach((n) => { n.lit = 0.5; });
      // Draw at the time the simulation reached. Wave rings measure their age
      // against it, and draw(0) made every ring born after t=0 negative-radius -
      // arc() throws on that, which blanked the whole app under reduced motion.
      draw(899 * 30);
      return;
    }

    const loop = (t: number) => {
      const dt = Math.min(48, last ? t - last : 16); last = t;
      if (ptr.x > -9000) ptr.on = 1;
      else ptr.on += (0 - ptr.on) * Math.min(1, dt / 260);
      step(t, dt); draw(t);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    const move = (e: PointerEvent) => {
      const r = cv!.getBoundingClientRect();
      ptr.x = e.clientX - r.left; ptr.y = e.clientY - r.top;
    };
    const leave = () => { ptr.x = -9999; ptr.y = -9999; };
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('pointerleave', leave);
    let resizeT = 0;
    const ro = new ResizeObserver(() => {
      const r = cv!.getBoundingClientRect();
      if (Math.abs(r.width - w) < 2 && Math.abs(r.height - h) < 2) return;
      // Rebuilding the lattice on every observer callback means the network
      // reshuffles continuously for the whole length of a drag-resize. Settle
      // first, then rebuild once.
      clearTimeout(resizeT);
      resizeT = window.setTimeout(layout, 140);
    });
    ro.observe(cv);
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); clearTimeout(resizeT);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerleave', leave);
    };
  }, []);

  return <canvas ref={ref} className={className} aria-hidden />;
}

const easeOut = (k: number) => 1 - Math.pow(1 - k, 3);

/** Canvas gradients need a colour with an alpha channel, and the tokens are
 *  opaque hex. Handles #rgb and #rrggbb; anything else is passed through so a
 *  future token format degrades to "no gradient" rather than to a crash. */
function withAlpha(hex: string, a: number) {
  const m = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return hex;
  let h = m[1];
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** Seeded, so the lattice is the same on every load. A layout that reshuffles on
 *  refresh reads as noise rather than as a network. */
function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
