// How the case page behaves on a graph of 2,000 wallets, measured in a real browser.
//
//   npm run build && node scripts/perf.mjs            (N=2000 by default)
//
// It serves the built bundle (`vite preview`), answers the page's /api requests itself with a
// synthetic case (scripts/big-graph.mjs: a shape, not data), and times: the page until the graph
// is drawn, frames while the graph is dragged, each "draw more" step, and the Wallets tab.
// Headless, without a GPU: a desk machine with one is faster than these figures.
import { spawn } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { bigCase } from './big-graph.mjs'
import { dom, launch, sleep, waitFor } from './browser.mjs'

const N = Number(process.env.N ?? 2000)
const PORT = 4183 // not 4190: fetch refuses the ports on its blocked list
const BASE = `http://127.0.0.1:${PORT}`
const ui = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const server = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], { cwd: ui, stdio: 'ignore' })
const browser = await launch({ port: 9336 })
const { page } = browser
const failures = []
const check = (name, value, limit, unit = 'ms') => {
  const ok = value <= limit
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}: ${Math.round(value)} ${unit} (limit ${limit})`)
  if (!ok) failures.push(name)
}

try {
  await waitFor(async () => (await fetch(BASE)).ok, 'vite preview')
  const c = bigCase(N)
  const answers = {
    [`/api/cases/${c.id}`]: c,
    '/api/auth/me': { auth_required: false, officer: null },
    '/api/audit': { total: 0, limit: 100, offset: 0, items: [], chain: null },
  }
  await page.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/*' }] })
  page.on('Fetch.requestPaused', ({ requestId, request }) => {
    const body = answers[new URL(request.url).pathname]
    void page.send('Fetch.fulfillRequest', {
      requestId,
      responseCode: body ? 200 : 404,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, { name: 'X-Data-Source', value: 'live' }],
      body: Buffer.from(JSON.stringify(body ?? { detail: 'Not part of the measurement.' })).toString('base64'),
    })
  })
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

  console.log(`A synthetic case of ${c.graph.nodes.length} wallets and ${c.graph.edges.length} transfers`)
  await page.send('Page.navigate', { url: `${BASE}/cases/${c.id}` })
  await waitFor(() => page.evaluate(`document.querySelectorAll('[role="img"] canvas').length > 0`), 'the graph')
  check('page open to graph drawn', await page.evaluate('performance.now()'), 2000)

  // Frames while the graph is dragged across the canvas, 90 steps.
  const box = await page.evaluate(`(() => { const r = document.querySelector('[role="img"]').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } })()`)
  await page.evaluate(`(() => { window.__frames = []; let last = performance.now(); const tick = (t) => { window.__frames.push(t - last); last = t; window.__raf = requestAnimationFrame(tick) }; window.__raf = requestAnimationFrame(tick) })()`)
  await page.send('Input.dispatchMouseEvent', { type: 'mousePressed', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  for (let i = 1; i <= 90; i++) {
    await page.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box.x + Math.sin(i / 8) * 180, y: box.y + Math.cos(i / 8) * 90, button: 'left' })
    await sleep(16)
  }
  await page.send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: box.x, y: box.y, button: 'left', clickCount: 1 })
  const frames = (await page.evaluate(`(cancelAnimationFrame(window.__raf), window.__frames.slice(2))`)).sort((a, b) => a - b)
  check('dragging the graph, median frame', frames[Math.floor(frames.length / 2)], 20)
  check('dragging the graph, 95th percentile frame', frames[Math.floor(frames.length * 0.95)], 50)

  // Each step is timed from the click to the second frame after it.
  const timed = async (js) =>
    page.evaluate(`new Promise((done) => { const t = performance.now(); ${js}; requestAnimationFrame(() => requestAnimationFrame(() => done(performance.now() - t))) })`)
  check('draw 50 more of hop 2', await timed(dom.clickText('Draw 50 more of hop 2')), 200)
  for (const hop of [3, 4, 5]) {
    if (await page.evaluate(`[...document.querySelectorAll('button')].some((b) => b.textContent.trim().startsWith('Draw hop ${hop}'))`))
      check(`draw hop ${hop}`, await timed(dom.clickText(`Draw hop ${hop}`)), 200)
  }
  check('open the Wallets tab (first 200 rows)', await timed(dom.clickText('Wallets', '[role="tab"]')), 300)
  check('open the Transfers tab (first 200 rows)', await timed(dom.clickText('Transfers', '[role="tab"]')), 300)
  check('open the Timeline tab', await timed(dom.clickText('Timeline', '[role="tab"]')), 300)
  const elements = await page.evaluate('document.querySelectorAll("*").length')
  check('elements on the page', elements, 15000, 'nodes')
} finally {
  await browser.close()
  server.kill()
}
if (failures.length) {
  console.error(`\n${failures.length} over the limit: ${failures.join('; ')}`)
  process.exit(1)
}
console.log('\nAll within the limits.')
