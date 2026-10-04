// Screenshots of the component kit, the shell, the case page, the request desk and the overview pages
// (dashboard, wallet, labels, model, watchlist), in both themes, into docs/screenshots/.
//
//   npm run dev                       (in another terminal; mock data, port 5173)
//   npm run screenshots               (or: BASE_URL=http://localhost:5183 npm run screenshots)
//   npm run screenshots -- case       (only the shots whose name starts with "case")
//
// LIVE_URL=http://localhost:5184 adds the shots of the real demo cases (`case-live-*`): the
// interface run with VITE_API=live against `make serve`, after `make demo`.
//
// It drives a Chromium-family browser already on this machine (Chrome, Brave, Edge, Chromium;
// or BROWSER=/path/to/binary) headless, over the DevTools protocol, with a throwaway profile.
// No dependency is installed and nothing is downloaded.
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const BASE = process.env.BASE_URL ?? 'http://localhost:5173'
const LIVE = process.env.LIVE_URL
const ONLY = process.argv[2]
const OUT = process.env.OUT_DIR ?? resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'screenshots')
const PORT = 9333

// A page has rendered once its fixtures are on it: a Hop Rail's stamp, or a table row's.
const STAMP = `document.querySelectorAll('[aria-label="Path of the funds"] [data-testid="outcome-stamp"], tbody tr [data-testid="outcome-stamp"]').length > 0`
// The case page: the stamp, and the graph's canvas drawn.
const CASE = `${STAMP} && document.querySelectorAll('[role="img"] canvas').length > 0`
const INTAKE = `document.querySelectorAll('[aria-label="Recorded demo cases"] button').length > 0`
const click = (selector) => `document.querySelector(${JSON.stringify(selector)}).click()`
const PICK_DEMO = click('[aria-label="Recorded demo cases"] button')
const GROUP = `[...document.querySelectorAll('button')].find((b) => b.getAttribute('aria-label') === 'Group exchange wallets').click()`
// Type the hero demo wallet (demo/cases.json, tron-coindcx) into the sheet, as React hears it.
const TYPE_HERO = `(() => {
  const input = document.querySelector('form[aria-label="Open a case"] input')
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c')
  input.dispatchEvent(new Event('input', { bubbles: true }))
})()`
const TICK_AGAIN = click('form[aria-label="Open a case"] input[type="checkbox"]')
const TRACE = click('form[aria-label="Open a case"] button[type="submit"]')

// The desk and the register: a status tag in a table row. An exchange's page: its facts. A request: the sheet.
const DESK = `document.querySelectorAll('tbody tr [data-testid="status-tag"]').length > 0`
const VASP = `document.querySelectorAll('dl dt').length > 0 && document.querySelectorAll('tbody tr').length > 0`
const LETTER = `document.querySelectorAll('.sheet table tbody tr').length > 0`
const DIALOG = `document.querySelectorAll('dialog[open] input[type="checkbox"]').length > 0`
const press = (text) => `[...document.querySelectorAll('button')].find((b) => b.textContent.trim().startsWith(${JSON.stringify(text)})).click()`
const APPROVE = press('Approve request')
const REPLY = press('Record reply')

// U4: the dashboard's counts; the label coverage; a table's rows; a plot; a wallet's record; the watchlist.
const COUNTS = `document.querySelectorAll('ul[aria-label="Counts"] li').length > 0`
const COVERAGE = `document.querySelectorAll('ul[aria-label="Labels by tier"] li').length > 0`
const ROWS = `document.querySelectorAll('tbody tr td a, tbody tr td button').length > 0`
const PLOT = `document.querySelectorAll('svg[role="group"] circle').length > 0`
const WALLET = `document.querySelectorAll('section[aria-label="On record against this address"] p').length > 0`
const WATCH = `document.querySelectorAll('form[aria-label="Watch a wallet"] input').length > 0`
const WATCHED = `document.querySelectorAll('ul[aria-label="Watched wallets"] li').length > 0`

const OKX = '/cases/demo-tron-okx'
const SHOTS = [
  // name, path, width, height, full page?, { ready, steps: [js to run | ms to wait], live }
  ['kit-light-1440', '/kit?theme=light', 1440, 900, true],
  ['kit-dark-1440', '/kit?theme=dark', 1440, 900, true],
  ['kit-light-1280', '/kit?theme=light', 1280, 800, true],
  ['kit-dark-1280', '/kit?theme=dark', 1280, 800, true],
  ['kit-shell-cases-light', '/cases?theme=light', 1440, 900, false],
  ['kit-shell-cases-dark', '/cases?theme=dark', 1440, 900, false],

  // --- U2: intake, the trace, the case page ------------------------------------------------
  ['case-intake-light', '/cases/new?theme=light', 1440, 900, false, { ready: INTAKE, steps: [PICK_DEMO, 200] }],
  ['case-intake-dark', '/cases/new?theme=dark', 1440, 900, false, { ready: INTAKE }],
  ['case-tracing-light', '/cases/new?theme=light', 1440, 900, false, { ready: INTAKE, steps: [PICK_DEMO, 200, TRACE, 1500] }],
  ['case-attributed-light', `${OKX}?theme=light`, 1440, 900, true, { ready: CASE }],
  ['case-attributed-dark', `${OKX}?theme=dark`, 1440, 900, true, { ready: CASE }],
  ['case-attributed-fold-1440', `${OKX}?theme=light`, 1440, 900, false, { ready: CASE }],
  ['case-attributed-fold-1280', `${OKX}?theme=light`, 1280, 800, false, { ready: CASE }],
  ['case-attributed-tablet', `${OKX}?theme=light`, 820, 1100, true, { ready: CASE }],
  ['case-wallet-selected', `${OKX}?theme=light&wallet=THS5KLm2HwoZyXt5XeVpfuhdKkXpotELsR`, 1440, 900, false, { ready: CASE }],
  ['case-grouped', `${OKX}?theme=light`, 1440, 900, false, { ready: CASE, steps: [GROUP, 600] }],
  ['case-tab-transfers', `${OKX}?theme=light&tab=transfers`, 1440, 900, true, { ready: CASE }],
  ['case-tab-wallets', `${OKX}?theme=light&tab=wallets`, 1440, 900, true, { ready: CASE }],
  ['case-tab-patterns', `${OKX}?theme=light&tab=patterns`, 1440, 900, true, { ready: CASE }],
  ['case-tab-audit', `${OKX}?theme=light&tab=audit`, 1440, 900, true, { ready: CASE }],
  ['case-insufficient-light', '/cases/demo-eth-abstain?theme=light', 1440, 900, true, { ready: CASE }],
  ['case-insufficient-dark', '/cases/demo-eth-abstain?theme=dark', 1440, 900, true, { ready: CASE }],
  ['case-sanctioned-light', '/cases/demo-tron-sanctioned?theme=light', 1440, 900, true, { ready: CASE }],
  ['case-sanctioned-dark', '/cases/demo-tron-sanctioned?theme=dark', 1440, 900, true, { ready: CASE }],

  // --- the real demo wallets, through the live API -----------------------------------------
  ['case-live-coindcx-light', '/cases/tron-coindcx?theme=light', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-coindcx-dark', '/cases/tron-coindcx?theme=dark', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-coindcx-inbound', '/cases/tron-coindcx?theme=light&tab=inbound', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-coindcx-audit', '/cases/tron-coindcx?theme=light&tab=audit', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-two-exchanges', '/cases/tron-htx-coindcx?theme=light', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-insufficient', '/cases/tron-abstain?theme=light', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-insufficient-fold', '/cases/tron-abstain?theme=light', 1440, 900, false, { ready: CASE, live: true }],
  ['case-live-insufficient-fold-dark', '/cases/tron-abstain?theme=dark', 1440, 900, false, { ready: CASE, live: true }],
  ['case-live-insufficient-patterns', '/cases/tron-abstain?theme=light&tab=patterns', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-bridge', '/cases/eth-bridge?theme=light', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-sanctioned', '/cases/tron-ofac?theme=light', 1440, 900, true, { ready: CASE, live: true }],
  ['case-live-bitcoin', '/cases/btc-htx?theme=light', 1440, 900, true, { ready: CASE, live: true }],
  // Last, because it changes the stored case: the hero wallet traced again from the cache while
  // watching (intake → trace → the rail extended, "Trace finished").
  ['case-live-traced', '/cases/new?theme=light', 1440, 900, false, { ready: INTAKE, live: true, steps: [TYPE_HERO, 200, TICK_AGAIN, TRACE, 4000] }],

  // --- U3: the request desk, an exchange's page, the letter, the register ---------------------
  ['desk-light', '/desk?theme=light', 1440, 900, true, { ready: DESK }],
  ['desk-dark', '/desk?theme=dark', 1440, 900, true, { ready: DESK }],
  ['desk-letter-demo', '/requests/demo-req-okx-001?theme=light', 1440, 900, true, { ready: LETTER }],
  ['desk-register-demo', '/requests?theme=light', 1440, 900, false, { ready: DESK }],
  // The real demo cases through the live API, after: a request to CoinDCX drafted, approved and
  // sent (req-2026-0001), one to HTX drafted (req-2026-0002), one to Bitget approved (0003) and a draft
  // withdrawn (0004). ui/src/test/fixtures/desk/record.py does that, then again with --more.
  ['desk-live-light', '/desk?theme=light', 1440, 900, true, { ready: DESK, live: true }],
  ['desk-live-dark', '/desk?theme=dark', 1440, 900, true, { ready: DESK, live: true }],
  ['desk-live-1280', '/desk?theme=light', 1280, 800, false, { ready: DESK, live: true }],
  ['desk-live-tablet', '/desk?theme=light', 820, 1100, true, { ready: DESK, live: true }],
  ['desk-live-draft-dialog', '/desk?theme=light&vasp=Bitget&case=eth-bitget', 1440, 900, false, { ready: DIALOG, live: true }],
  ['desk-live-draft-dialog-dark', '/desk?theme=dark&vasp=Bitget&case=eth-bitget', 1440, 900, false, { ready: DIALOG, live: true }],
  ['desk-live-vasp-coindcx', '/vasps/CoinDCX?theme=light', 1440, 900, true, { ready: VASP, live: true }],
  ['desk-live-vasp-coindcx-dark', '/vasps/CoinDCX?theme=dark', 1440, 900, true, { ready: VASP, live: true }],
  ['desk-live-vasp-htx', '/vasps/HTX?theme=light', 1440, 900, true, { ready: VASP, live: true }],
  ['desk-live-vasp-kucoin', '/vasps/KuCoin?theme=light', 1440, 900, true, { ready: VASP, live: true }],
  ['desk-live-letter-draft', '/requests/req-2026-0002?theme=light', 1440, 900, true, { ready: LETTER, live: true, pdf: true }],
  ['desk-live-letter-draft-dark', '/requests/req-2026-0002?theme=dark', 1440, 900, true, { ready: LETTER, live: true }],
  ['desk-live-letter-approve', '/requests/req-2026-0002?theme=light', 1440, 900, false, { ready: LETTER, live: true, steps: [APPROVE, 300] }],
  ['desk-live-letter-approved', '/requests/req-2026-0003?theme=light', 1440, 900, true, { ready: LETTER, live: true, pdf: true }],
  ['desk-live-letter-sent', '/requests/req-2026-0001?theme=light', 1440, 900, true, { ready: LETTER, live: true }],
  ['desk-live-letter-sent-1280', '/requests/req-2026-0001?theme=light', 1280, 800, false, { ready: LETTER, live: true }],
  ['desk-live-letter-sent-tablet', '/requests/req-2026-0001?theme=light', 820, 1100, true, { ready: LETTER, live: true }],
  ['desk-live-letter-reply', '/requests/req-2026-0001?theme=light', 1440, 900, false, { ready: LETTER, live: true, steps: [REPLY, 300] }],
  ['desk-live-register', '/requests?theme=light', 1440, 900, false, { ready: DESK, live: true }],
  ['desk-live-register-dark', '/requests?theme=dark', 1440, 900, false, { ready: DESK, live: true }],
  ['desk-live-register-1280', '/requests?theme=light', 1280, 800, false, { ready: DESK, live: true }],

  // --- U4: dashboard, a wallet, the labels explorer, the model, the watchlist -----------------
  ['overview-dashboard-light', '/dashboard?theme=light', 1440, 900, true, { ready: COUNTS }],
  ['overview-dashboard-dark', '/dashboard?theme=dark', 1440, 900, true, { ready: COUNTS }],
  ['overview-labels-light', '/labels?theme=light', 1440, 900, true, { ready: COVERAGE }],
  ['overview-labels-search', '/labels?theme=light&q=coindcx', 1440, 900, false, { ready: ROWS }],
  ['overview-model-light', '/model?theme=light', 1440, 900, true, { ready: PLOT }],
  ['overview-model-dark', '/model?theme=dark', 1440, 900, true, { ready: PLOT }],
  ['overview-wallet-demo', '/wallets/tron/THS5KLm2HwoZyXt5XeVpfuhdKkXpotELsR?theme=light', 1440, 900, true, { ready: WALLET }],
  ['overview-watchlist-empty', '/watchlist?theme=light', 1440, 900, false, { ready: WATCH }],
  ['overview-cases-filtered', '/cases?theme=light&outcome=ATTRIBUTED', 1440, 900, false, { ready: STAMP }],
  // The real demo cases through the live API. The watchlist shots need watched wallets: the U4 notes in
  // PROGRESS.md say how the ones pictured were added.
  ['overview-live-dashboard-light', '/dashboard?theme=light', 1440, 900, true, { ready: COUNTS, live: true }],
  ['overview-live-dashboard-dark', '/dashboard?theme=dark', 1440, 900, true, { ready: COUNTS, live: true }],
  ['overview-live-dashboard-1280', '/dashboard?theme=light', 1280, 800, false, { ready: COUNTS, live: true }],
  ['overview-live-dashboard-tablet', '/dashboard?theme=light', 820, 1100, true, { ready: COUNTS, live: true }],
  ['overview-live-labels-light', '/labels?theme=light', 1440, 900, true, { ready: COVERAGE, live: true }],
  ['overview-live-labels-dark', '/labels?theme=dark', 1440, 900, true, { ready: COVERAGE, live: true }],
  ['overview-live-labels-derived-tron', '/labels?theme=light&chain=tron&tier=derived&q=coindcx', 1440, 900, false, { ready: ROWS, live: true }],
  ['overview-live-model-tron', '/model?theme=light', 1440, 900, true, { ready: PLOT, live: true }],
  ['overview-live-model-tron-dark', '/model?theme=dark', 1440, 900, true, { ready: PLOT, live: true }],
  ['overview-live-model-ethereum', '/model?theme=light&chain=ethereum', 1440, 900, true, { ready: PLOT, live: true }],
  ['overview-live-model-1280', '/model?theme=light', 1280, 800, false, { ready: PLOT, live: true }],
  ['overview-live-wallet-traced', '/wallets/tron/TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c?theme=light', 1440, 900, true, { ready: WALLET, live: true }],
  ['overview-live-wallet-deposit', '/wallets/tron/TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5?theme=light', 1440, 900, true, { ready: WALLET, live: true }],
  ['overview-live-wallet-deposit-dark', '/wallets/tron/TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5?theme=dark', 1440, 900, true, { ready: WALLET, live: true }],
  ['overview-live-wallet-sanctioned', '/wallets/tron/TFdHux43bs21qRsygv5WQWfgtbQeT6nXey?theme=light', 1440, 900, true, { ready: WALLET, live: true }],
  ['overview-live-watchlist-light', '/watchlist?theme=light', 1440, 900, true, { ready: WATCHED, live: true }],
  ['overview-live-watchlist-dark', '/watchlist?theme=dark', 1440, 900, true, { ready: WATCHED, live: true }],
  ['overview-live-cases-open', '/cases?theme=light&open=1', 1440, 900, false, { ready: STAMP, live: true }],
].filter(([name, , , , , opts]) => (!ONLY || name.startsWith(ONLY)) && (!opts?.live || LIVE))

const CANDIDATES = [
  process.env.BROWSER,
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
].filter(Boolean)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function waitFor(fn, what, tries = 60) {
  for (let i = 0; i < tries; i++) {
    try {
      const v = await fn()
      if (v) return v
    } catch {
      /* not up yet */
    }
    await sleep(250)
  }
  throw new Error(`Timed out waiting for ${what}`)
}

/** One DevTools-protocol session on one tab. */
function session(wsUrl) {
  const ws = new WebSocket(wsUrl)
  let next = 1
  const pending = new Map()
  ws.addEventListener('message', (e) => {
    const msg = JSON.parse(e.data)
    if (msg.id && pending.has(msg.id)) {
      const { ok, fail } = pending.get(msg.id)
      pending.delete(msg.id)
      if (msg.error) fail(new Error(msg.error.message))
      else ok(msg.result)
    }
  })
  const opened = new Promise((ok, fail) => {
    ws.addEventListener('open', ok)
    ws.addEventListener('error', () => fail(new Error('Could not connect to the browser')))
  })
  const send = async (method, params = {}) => {
    await opened
    const id = next++
    return new Promise((ok, fail) => {
      pending.set(id, { ok, fail })
      ws.send(JSON.stringify({ id, method, params }))
    })
  }
  const evaluate = async (expression) =>
    (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value
  return { send, evaluate, close: () => ws.close() }
}

const browserPath = CANDIDATES.find((p) => existsSync(p))
if (!browserPath) {
  console.error('No Chromium-family browser found. Set BROWSER=/path/to/chrome and run again.')
  process.exit(1)
}

for (const url of [BASE, LIVE].filter(Boolean)) {
  try {
    await fetch(url)
  } catch {
    console.error(`Nothing answers at ${url}. Start the interface first (npm run dev), or set BASE_URL / LIVE_URL`)
    process.exit(1)
  }
}

const profile = mkdtempSync(join(tmpdir(), 'vaspfusion-shots-'))
const browser = spawn(
  browserPath,
  [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--hide-scrollbars',
    '--disable-gpu',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

try {
  mkdirSync(OUT, { recursive: true })
  const targets = await waitFor(async () => (await fetch(`http://127.0.0.1:${PORT}/json`)).json(), 'the browser to start')
  const page = session(targets.find((t) => t.type === 'page').webSocketDebuggerUrl)
  await page.send('Page.enable')

  for (const [name, path, width, height, full, opts = {}] of SHOTS) {
    const metrics = { width, height, deviceScaleFactor: 1, mobile: false }
    await page.send('Emulation.setDeviceMetricsOverride', metrics)
    await page.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    })
    // A fresh document for every shot: the same route with another theme is otherwise not reloaded.
    await page.send('Page.navigate', { url: 'about:blank' })
    await page.send('Page.navigate', { url: (opts.live ? LIVE : BASE) + path })
    // Loaded = fonts in, and what the page shows is on it.
    await waitFor(
      () =>
        page.evaluate(`document.fonts.ready.then(() =>
          location.pathname + location.search === ${JSON.stringify(path)} &&
          document.fonts.check('16px "IBM Plex Sans"') &&
          (${opts.ready ?? STAMP}))`),
      `${path} to render`,
    )
    await sleep(300)
    for (const step of opts.steps ?? []) {
      if (typeof step === 'number') await sleep(step)
      else await page.evaluate(step)
    }
    if (full) {
      // Make the window as tall as the page, so the rail runs the whole height of the picture.
      const pageHeight = await page.evaluate('document.documentElement.scrollHeight')
      await page.send('Emulation.setDeviceMetricsOverride', { ...metrics, height: pageHeight })
      await sleep(400)
    }
    const { data } = await page.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
    console.log(`${name}.png`)
  }
  page.close()

  // What "Print or save as PDF" gives: the page's own @page size, margins and margin boxes.
  // Each in a tab of its own, printed last: a tab that has printed does not load another page.
  for (const [name, path, , , , opts = {}] of SHOTS.filter((shot) => shot[5]?.pdf)) {
    const url = (opts.live ? LIVE : BASE) + path
    const made = await (await fetch(`http://127.0.0.1:${PORT}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json()
    const tab = session(made.webSocketDebuggerUrl)
    await waitFor(
      () => tab.evaluate(`document.fonts.ready.then(() => document.fonts.check('16px "IBM Plex Sans"') && (${opts.ready ?? STAMP}))`),
      `${path} to render`,
    )
    await sleep(500)
    const pdf = await tab.send('Page.printToPDF', { preferCSSPageSize: true, printBackground: true, displayHeaderFooter: false })
    writeFileSync(join(OUT, `${name}.pdf`), Buffer.from(pdf.data, 'base64'))
    console.log(`${name}.pdf`)
    tab.close()
  }
} finally {
  browser.kill()
  await sleep(300)
  rmSync(profile, { recursive: true, force: true })
}
