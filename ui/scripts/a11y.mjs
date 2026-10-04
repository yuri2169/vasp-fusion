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

const api = async (method, path, body) => {
  const r = await fetch(BASE + path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body && JSON.stringify(body) })
  return r.ok ? r.json() : null
}
// A request to look at: the newest one, or a draft made now (it stays a draft).
const requests = (await api('GET', '/api/requests'))?.items ?? []
const request = requests[0] ?? (await api('POST', '/api/requests', { vasp: 'CoinDCX', case_ids: ['tron-coindcx'], asks: ['kyc'], officer: 'Accessibility audit' }))

const ROUTES = [
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
  '/cases/btc-htx',
  '/desk',
  '/desk?vasp=CoinDCX&case=tron-htx-coindcx',
  '/requests',
  request && `/requests/${request.id}`,
  '/vasps/CoinDCX',
  '/dashboard',
  '/labels',
  '/labels?q=CoinDCX',
  '/model',
  '/model?chain=ethereum',
  '/watchlist',
  `/wallets/tron/${HERO}`,
  '/nowhere',
].filter(Boolean)

const READY = `document.fonts.ready.then(() => !!document.querySelector('main h1, main [role="alert"]') && !document.querySelector('main [aria-busy="true"]'))`

const browser = await launch({ port: 9337 })
const { page } = browser
let broken = 0
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
        await page.evaluate(axe)
        const found = await page.evaluate(`axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] }).then((r) => r.violations.map((v) => ({
          id: v.id, impact: v.impact, help: v.help, n: v.nodes.length,
          first: v.nodes.slice(0, 3).map((x) => x.target.join(' ') + ' :: ' + (x.failureSummary ?? '').split('\\n').slice(1, 2).join(' ').trim().slice(0, 160)),
        })))`)
        console.log(`${found.length ? 'FAIL' : 'PASS'}  ${theme.padEnd(5)} ${path}`)
        for (const v of found) {
          broken += 1
          console.log(`      ${v.impact}: ${v.id} (${v.n}) ${v.help}`)
          for (const line of v.first) console.log(`        ${line}`)
        }
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
