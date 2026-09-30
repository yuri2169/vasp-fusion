/** Sonar sweep — the scoring screen's companion animation.
 *
 * Chosen over a character mascot deliberately. This is a tool that will be
 * demonstrated to a national technical agency, and a cartoon undercuts the one
 * thing the interface is trying to earn. A sweep reads as apparatus: it is the
 * same idea as the landing field's vantage point, rotated - something listening,
 * finding contacts, losing them again.
 *
 * The blips are not random decoration. One appears when the sweep passes a
 * bearing that currently holds a contact, and contacts are seeded per stage, so
 * the display genuinely changes as the pipeline advances rather than looping
 * identically for 105 seconds.
 */
import { useEffect, useRef } from 'react';

type Blip = { bearing: number; radius: number; lit: number };

export function Sonar({ stage, size = 132 }: { stage: number; size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef(stage);
  stageRef.current = stage;

  useEffect(() => {
    const cv = ref.current; if (!cv) return;
    const ctx = cv.getContext('2d'); if (!ctx) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    cv.width = size * dpr; cv.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const c = size / 2, R = size / 2 - 6;

    let blips: Blip[] = [];
    let lastStage = -1;
    const seed = (s: number) => {
      // Deterministic per stage: the same stage always shows the same contacts,
      // so the panel is not a lava lamp - it is a readout that changes when the
      // pipeline changes.
      let a = (s + 1) * 2654435761 >>> 0;
      const rnd = () => { a = (a * 1664525 + 1013904223) >>> 0; return a / 4294967296; };
      blips = Array.from({ length: 3 + Math.floor(rnd() * 3) }, () => ({
        bearing: rnd() * Math.PI * 2,
        radius: 0.32 + rnd() * 0.6,
        lit: 0,
      }));
    };

    let raf = 0, angle = -Math.PI / 2, last = 0;

    const draw = (t: number) => {
      const dt = Math.min(48, last ? t - last : 16); last = t;
      if (stageRef.current !== lastStage) { lastStage = stageRef.current; seed(lastStage); }

      const cs = getComputedStyle(document.documentElement);
      const tok = (n: string, f: string) => cs.getPropertyValue(n).trim() || f;
      const chain = tok('--chain', '#2D6A9F');
      const rule = tok('--rule', '#C3CCD4');

      ctx.clearRect(0, 0, size, size);

      // Range rings and bearing cross - the instrument's furniture.
      ctx.strokeStyle = rule; ctx.lineWidth = 1;
      [0.34, 0.67, 1].forEach((r) => {
        ctx.globalAlpha = r === 1 ? 0.7 : 0.35;
        ctx.beginPath(); ctx.arc(c, c, R * r, 0, Math.PI * 2); ctx.stroke();
      });
      ctx.globalAlpha = 0.28;
      ctx.beginPath();
      ctx.moveTo(c - R, c); ctx.lineTo(c + R, c);
      ctx.moveTo(c, c - R); ctx.lineTo(c, c + R);
      ctx.stroke();

      const prev = angle;
      if (!reduced) angle += (dt / 1000) * (Math.PI * 2 / 3.4);   // one turn / 3.4s

      // The sweep: a wedge trailing behind the leading edge, drawn as stacked
      // segments rather than a conic gradient - conic support is still uneven and
      // this costs 22 fills once per frame.
      const TRAIL = Math.PI * 0.55, STEPS = 22;
      for (let i = 0; i < STEPS; i++) {
        const a0 = angle - (TRAIL * (i + 1)) / STEPS;
        const a1 = angle - (TRAIL * i) / STEPS;
        ctx.beginPath(); ctx.moveTo(c, c); ctx.arc(c, c, R, a0, a1); ctx.closePath();
        ctx.fillStyle = chain;
        ctx.globalAlpha = 0.16 * (1 - i / STEPS) ** 1.6;
        ctx.fill();
      }
      ctx.beginPath(); ctx.moveTo(c, c);
      ctx.lineTo(c + Math.cos(angle) * R, c + Math.sin(angle) * R);
      ctx.strokeStyle = chain; ctx.lineWidth = 1.4; ctx.globalAlpha = 0.9; ctx.stroke();

      // A contact lights when the sweep crosses its bearing, then decays.
      const norm = (x: number) => ((x % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
      blips.forEach((b) => {
        const a = norm(b.bearing), p = norm(prev), n = norm(angle);
        const crossed = p <= n ? a > p && a <= n : a > p || a <= n;
        if (crossed) b.lit = 1;
        b.lit *= Math.pow(0.5, dt / 900);
        if (b.lit < 0.02) return;
        const x = c + Math.cos(b.bearing) * R * b.radius;
        const y = c + Math.sin(b.bearing) * R * b.radius;
        ctx.beginPath(); ctx.arc(x, y, 2.6, 0, Math.PI * 2);
        ctx.fillStyle = chain; ctx.globalAlpha = b.lit; ctx.fill();
        ctx.beginPath(); ctx.arc(x, y, 2.6 + (1 - b.lit) * 7, 0, Math.PI * 2);
        ctx.strokeStyle = chain; ctx.lineWidth = 1;
        ctx.globalAlpha = b.lit * 0.35; ctx.stroke();
      });
      ctx.globalAlpha = 1;

      if (!reduced) raf = requestAnimationFrame(draw);
    };

    if (reduced) { seed(stageRef.current); draw(0); }
    else raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return <canvas ref={ref} style={{ width: size, height: size }} aria-hidden />;
}
