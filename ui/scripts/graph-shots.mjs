// Pictures of the Fund flow panel in the states a recorded case does not reach by itself: a
// fan of many payers, closed and opened. The case is a synthetic SHAPE (scripts/big-graph.mjs),
// answered to the page by this script; nothing here is data.
//
//   node scripts/graph-shots.mjs                 OUT_DIR=docs/screenshots, PAYERS=50
//   CASE_FILE=case.json node scripts/graph-shots.mjs     a stored case instead (GET /api/cases/<id>)
//   CONTEXT_FILE=context.json                    its context (GET /api/cases/<id>/context), for the context pictures
import { spawn } from 'node:child_process'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { fanCase } from './big-graph.mjs'
import { dom, launch, sleep, waitFor } from './browser.mjs'

const here = dirname(fileURLToPath(import.meta.url))
const ui = resolve(here, '..')
const OUT = process.env.OUT_DIR ?? resolve(ui, '..', 'docs', 'screenshots')
const PORT = 4184
const BASE = `http://127.0.0.1:${PORT}`
const PAYERS = Number(process.env.PAYERS ?? 50)
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null

mkdirSync(OUT, { recursive: true })
const server = spawn('npx', ['vite', '--port', String(PORT), '--strictPort', '--host', '127.0.0.1'], { cwd: ui, stdio: 'ignore', env: { ...process.env, VITE_API: 'live' } })
const browser = await launch({ port: 9337, gl: true })
const { page } = browser

try {
  await waitFor(async () => (await fetch(BASE)).ok, 'the dev server', 60000)
  const stored = process.env.CASE_FILE ? JSON.parse(readFileSync(process.env.CASE_FILE, 'utf8')) : null
  const context = process.env.CONTEXT_FILE ? JSON.parse(readFileSync(process.env.CONTEXT_FILE, 'utf8')) : null
  const c = stored ?? fanCase(PAYERS)
  const name = stored ? `graph-${c.id}` : `graph-fan-${PAYERS}`
  const answers = {
    [`/api/cases/${c.id}`]: c,
    ...(context ? { [`/api/cases/${c.id}/context`]: context } : {}),
    '/api/auth/me': { auth_required: false, officer: null },
    '/api/audit': { total: 0, limit: 100, offset: 0, items: [], chain: null },
  }
  await page.send('Fetch.enable', { patterns: [{ urlPattern: '*/api/*' }] })
  page.on('Fetch.requestPaused', ({ requestId, request }) => {
    const path = new URL(request.url).pathname
    // the dev server's own files under src/api/ are not the API
    if (!path.startsWith('/api/')) return void page.send('Fetch.continueRequest', { requestId })
    const body = answers[path]
    void page.send('Fetch.fulfillRequest', {
      requestId,
      responseCode: body ? 200 : 404,
      responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, { name: 'X-Data-Source', value: 'live' }],
      body: Buffer.from(JSON.stringify(body ?? { detail: 'Not part of the picture.' })).toString('base64'),
    })
  })
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 2, mobile: false })
  await page.send('Page.addScriptToEvaluateOnNewDocument', { source: `try { localStorage.setItem('vaspfusion.theme', 'system') } catch (e) {}` })

  const panel = `document.querySelector('section[aria-labelledby$="-title"]:has([role="img"])')`
  const save = async (state, theme) => {
    if (ONLY && !ONLY.includes(state)) return
    await sleep(700)
    const clip = await page.evaluate(`(() => { const r = ${panel}.getBoundingClientRect(); return { x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: r.height, scale: 1 } })()`)
    const { data } = await page.send('Page.captureScreenshot', { format: 'png', clip, captureBeyondViewport: true })
    writeFileSync(join(OUT, `final-${name}-${state}-${theme}.png`), Buffer.from(data, 'base64'))
    console.log(`final-${name}-${state}-${theme}.png`)
  }
  const click = (text) => page.evaluate(dom.clickText(text))
  const has = (text) => page.evaluate(`[...document.querySelectorAll('button')].some((b) => (b.getAttribute('aria-label') ?? b.textContent).trim().startsWith(${JSON.stringify(text)}))`)
  // a click on the canvas where a node is drawn
  const tap = async (id) => {
    const at = await page.evaluate(`(() => { const cy = window.__flowCy; const n = cy.getElementById(${JSON.stringify(id)}); const p = n.renderedPosition(); const r = cy.container().getBoundingClientRect(); return { x: r.left + p.x, y: r.top + p.y } })()`)
    for (const type of ['mousePressed', 'mouseReleased']) await page.send('Input.dispatchMouseEvent', { type, x: at.x, y: at.y, button: 'left', clickCount: 1 })
  }

  for (const theme of ['light', 'dark']) {
    await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: 'reduce' }] })
    await page.send('Page.navigate', { url: `${BASE}/cases/${c.id}` })
    await waitFor(() => page.evaluate(`document.querySelectorAll('[role="img"] canvas').length > 0 && !!window.__flowCy`), 'the graph', 60000).catch(async (e) => {
      console.error(await page.evaluate('document.body.innerText.slice(0, 600)'))
      throw e
    })
    if (process.env.DEBUG) console.log(await page.evaluate(`JSON.stringify({ all: window.__flowCy.elements().boundingBox(), nodes: window.__flowCy.nodes().boundingBox(), bad: window.__flowCy.edges().filter((e) => !isFinite(e.boundingBox().w)).map((e) => e.id()), size: [window.__flowCy.width(), window.__flowCy.height()], zoom: window.__flowCy.zoom(), pan: window.__flowCy.pan() })`))
    await save('default', theme)
    const fan = await page.evaluate(`window.__flowCy.nodes('[kind = "fan"]').map((n) => n.id())[0] ?? null`)
    if (fan) {
      await tap(fan)
      await waitFor(() => has('Collapse the wallets'), 'the fan to open')
      await click('Fit')
      await save('fan-open', theme)
      await click('Collapse the wallets')
    }
    if (context && (await has('Show all context'))) {
      await click('Show all context')
      await waitFor(() => has('Hide context'), 'the context')
      await click('Fit')
      await save('context', theme)
    }
    if (await page.evaluate(`!!document.querySelector('input[type="radio"][value="3d"]:not(:disabled)')`)) {
      await page.evaluate(`document.querySelector('input[type="radio"][value="3d"]').click()`)
      await waitFor(() => page.evaluate(`!!document.querySelector('[data-testid="flow-3d"] canvas')`), 'the 3D view', 30000)
      await sleep(1500)
      await save('3d', theme)
    }
  }
} finally {
  await browser.close()
  server.kill()
}
