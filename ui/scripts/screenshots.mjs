// Screenshots of the component kit and the shell, in both themes, into docs/screenshots/.
//
//   npm run dev                       (in another terminal; mock data, port 5173)
//   npm run screenshots               (or: BASE_URL=http://localhost:5183 npm run screenshots)
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
const OUT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'screenshots')
const PORT = 9333

const SHOTS = [
  // name, path, width, height, full page?
  ['kit-light-1440', '/kit?theme=light', 1440, 900, true],
  ['kit-dark-1440', '/kit?theme=dark', 1440, 900, true],
  ['kit-light-1280', '/kit?theme=light', 1280, 800, true],
  ['kit-dark-1280', '/kit?theme=dark', 1280, 800, true],
  ['kit-shell-cases-light', '/cases?theme=light', 1440, 900, false],
  ['kit-shell-cases-dark', '/cases?theme=dark', 1440, 900, false],
  ['kit-shell-case-light', '/cases/demo-tron-okx?theme=light', 1440, 900, false],
  ['kit-shell-case-dark', '/cases/demo-tron-okx?theme=dark', 1440, 900, false],
  ['kit-shell-case-light-1280', '/cases/demo-tron-okx?theme=light', 1280, 800, false],
  ['kit-shell-case-tablet', '/cases/demo-eth-abstain?theme=light', 820, 1000, false],
]

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

try {
  await fetch(BASE)
} catch {
  console.error(`Nothing answers at ${BASE}. Start the interface first (npm run dev), or set BASE_URL`)
  process.exit(1)
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

  for (const [name, path, width, height, full] of SHOTS) {
    const metrics = { width, height, deviceScaleFactor: 1, mobile: false }
    await page.send('Emulation.setDeviceMetricsOverride', metrics)
    await page.send('Emulation.setEmulatedMedia', {
      features: [{ name: 'prefers-reduced-motion', value: 'reduce' }],
    })
    await page.send('Page.navigate', { url: BASE + path })
    // Loaded = fonts in, and the fixtures on the page (a Hop Rail or a table row has rendered).
    await waitFor(
      () =>
        page.evaluate(`document.fonts.ready.then(() =>
          location.pathname + location.search === ${JSON.stringify(path)} &&
          document.fonts.check('16px "IBM Plex Sans"') &&
          document.querySelectorAll('[aria-label="Path of the funds"] [data-testid="outcome-stamp"], tbody tr [data-testid="outcome-stamp"]').length > 0)`),
      `${path} to render`,
    )
    await sleep(300)
    if (full) {
      // Make the window as tall as the page, so the rail runs the whole height of the picture.
      const pageHeight = await page.evaluate('document.documentElement.scrollHeight')
      await page.send('Emulation.setDeviceMetricsOverride', { ...metrics, height: pageHeight })
      await sleep(300)
    }
    const { data } = await page.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
    console.log(`docs/screenshots/${name}.png`)
  }
  page.close()
} finally {
  browser.kill()
  await sleep(300)
  rmSync(profile, { recursive: true, force: true })
}
