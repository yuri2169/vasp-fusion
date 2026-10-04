// The accessibility audit (U5): every screen, in both themes, through axe-core's WCAG 2.1 A and AA
// rules and its best practices; then a keyboard-only walk that records where Tab goes.
//
//   make serve            (the API serving the built interface, after `make demo`)
//   node scripts/a11y.mjs                 BASE_URL=http://127.0.0.1:8000 by default
//   node scripts/a11y.mjs keys            only the keyboard walk
//
// axe-core is a development dependency read from node_modules and injected into the page; it is
// never part of the bundle. Exit code 1 if any rule is broken.
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { launch, sleep, waitFor } from './browser.mjs'

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8000'
const ONLY = process.argv[2]
const here = dirname(fileURLToPath(import.meta.url))
const axe = readFileSync(resolve(here, '..', 'node_modules', 'axe-core', 'axe.min.js'), 'utf8')
const HERO = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c'

const officer = JSON.parse(readFileSync(resolve(here, '..', '..', 'demo', 'officer.json'), 'utf8'))
const browser = await launch({ port: 9337 })
const { page } = browser
let broken = 0

const AXE = `axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] }).then((r) => r.violations.map((v) => ({
  id: v.id, impact: v.impact, help: v.help, n: v.nodes.length,
  first: v.nodes.slice(0, 3).map((x) => x.target.join(' ') + ' :: ' + (x.failureSummary ?? '').split('\\n').slice(1, 2).join(' ').trim().slice(0, 160)),
})))`
const audit = async (name) => {
  await page.evaluate(axe)
  const found = await page.evaluate(AXE)
  console.log(`${found.length ? 'FAIL' : 'PASS'}  ${name}`)
  for (const v of found) {
    broken += 1
    console.log(`      ${v.impact}: ${v.id} (${v.n}) ${v.help}`)
    for (const line of v.first) console.log(`        ${line}`)
  }
}

// The API is spoken to from inside the page, so a server that asks for a login is signed in to once
// (the published demonstration account) and the session cookie serves every later call.
// The app opens light by default; the sign-in audit chooses the theme through the emulated device.
await page.send('Page.addScriptToEvaluateOnNewDocument', { source: `try { localStorage.setItem('vaspfusion.theme', 'system') } catch (e) {}` })
await page.send('Page.navigate', { url: BASE + '/' })
await waitFor(() => page.evaluate(`!!document.querySelector('h1')`), 'the first screen')
const api = (method, path, body) =>
  page.evaluate(`fetch(${JSON.stringify(path)}, { method: ${JSON.stringify(method)}, headers: { 'Content-Type': 'application/json' }, body: ${body ? JSON.stringify(JSON.stringify(body)) : 'undefined'} }).then((r) => (r.ok ? r.json() : null))`)
if ((await api('GET', '/api/auth/me'))?.auth_required) {
  for (const theme of ['light', 'dark']) {
    await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }] })
    await sleep(300)
    await audit(`${theme.padEnd(5)} the sign-in page`)
  }
  await api('POST', '/api/auth/login', { username: officer.username, password: officer.password })
}
// A request to look at: the newest one, or a draft made now (it stays a draft).
const requests = (await api('GET', '/api/requests'))?.items ?? []
const request = requests[0] ?? (await api('POST', '/api/requests', { vasp: 'CoinDCX', case_ids: ['tron-coindcx'], asks: ['kyc'], officer: 'Accessibility audit' }))

const ROUTES = [
  '/',
  '/cases',
  '/cases/new',
  '/cases/tron-coindcx',
  '/cases/tron-coindcx?tab=transfers',
  '/cases/tron-coindcx?tab=wallets',
  '/cases/tron-coindcx?tab=patterns',
  '/cases/tron-coindcx?tab=inbound',
  '/cases/tron-coindcx?tab=audit',
  `/cases/tron-coindcx?wallet=${HERO}`,
  '/cases/tron-abstain',
  '/cases/tron-ofac',
  '/cases/tron-terror-link', // threat chips on the header, the rail and the alerts
  '/cases?threat=any',
  '/cases/btc-htx',
  '/desk',
  '/desk?vasp=CoinDCX&case=tron-htx-coindcx',
  '/requests',
  request && `/requests/${request.id}`,
  '/vasps/CoinDCX',
  '/dashboard',
  '/labels',
  '/labels?q=CoinDCX',
  '/labels?threat=terrorism_financing',
  '/wallets/tron/TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ', // a listed address: the chip in the title
  '/model',
  '/model?chain=ethereum',
  '/watchlist',
  `/wallets/tron/${HERO}`,
  '/nowhere',
].filter(Boolean)

const READY = `document.fonts.ready.then(() => !!document.querySelector('main h1, main [role="alert"]') && !document.querySelector('main [aria-busy="true"]'))`

try {
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
  await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] })
  const open = async (path, theme) => {
    await page.send('Page.navigate', { url: 'about:blank' })
    await page.send('Page.navigate', { url: `${BASE}${path}${path.includes('?') ? '&' : '?'}theme=${theme}` })
    await waitFor(() => page.evaluate(READY), `${path} to render`)
    await sleep(350)
  }

  if (ONLY !== 'keys')
    for (const theme of ['light', 'dark'])
      for (const path of ROUTES) {
        await open(path, theme)
        await audit(`${theme.padEnd(5)} ${path}`)
      }

  // --- keyboard only: where Tab goes, and whether the place is visibly marked ---------------
  const key = async (name, code, keyCode, shift = false) => {
    for (const type of ['keyDown', 'keyUp'])
      await page.send('Input.dispatchKeyEvent', { type, key: name, code, windowsVirtualKeyCode: keyCode, modifiers: shift ? 8 : 0 })
  }
  const WHERE = `(() => { const el = document.activeElement; if (!el || el === document.body) return null
    const name = (el.getAttribute('aria-label') || el.innerText || el.getAttribute('placeholder') || el.getAttribute('title') || el.value || '').trim().replace(/\\s+/g, ' ').slice(0, 60)
    const s = getComputedStyle(el); const r = el.getBoundingClientRect()
    const marked = (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'
    return { tag: el.tagName.toLowerCase(), role: el.getAttribute('role'), name, marked, shown: r.width > 0 && r.height > 0 } })()`
  for (const path of ['/cases', '/cases/tron-coindcx', '/desk', request && `/requests/${request.id}`].filter(Boolean)) {
    await open(path, 'light')
    console.log(`\nTab order on ${path}`)
    const seen = []
    for (let i = 0; i < 60; i++) {
      await key('Tab', 'Tab', 9)
      const at = await page.evaluate(WHERE)
      if (!at) break
      const line = `${at.tag}${at.role ? `[${at.role}]` : ''} "${at.name}"`
      if (seen.includes(line) && seen.length > 8 && line === seen[0]) break
      seen.push(line)
      const fault = !at.marked ? '   <-- focus is not visibly marked' : !at.shown ? '   <-- focus is on something not shown' : !at.name ? '   <-- no name' : ''
      if (fault) broken += 1
      if (i < 28 || fault) console.log(`  ${String(i + 1).padStart(2)}. ${line}${fault}`)
    }
    console.log(`  (${seen.length} stops)`)
  }
} finally {
  await browser.close()
}
if (broken) {
  console.error(`\n${broken} finding(s).`)
  process.exit(1)
}
console.log('\nNo finding.')
