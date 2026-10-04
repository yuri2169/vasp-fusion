// The final pictures of every screen, in light and dark, from the running tool (U5):
// docs/screenshots/final-<screen>-<theme>.png. Run it after scripts/demo-flow.mjs on the same
// server, so the desk holds the request the flow sent.
//
//   node scripts/final-shots.mjs            BASE_URL=http://127.0.0.1:8000, OUT_DIR=docs/screenshots
//   ONLY=threat node scripts/final-shots.mjs   only the screens whose name contains "threat"
//
// It signs in with the published demonstration account when the server asks for a login.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { dom, launch, sleep, waitFor } from './browser.mjs'

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8000'
const here = dirname(fileURLToPath(import.meta.url))
const OUT = process.env.OUT_DIR ?? resolve(here, '..', '..', 'docs', 'screenshots')
const officer = JSON.parse(readFileSync(resolve(here, '..', '..', 'demo', 'officer.json'), 'utf8'))
const HERO = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c'
// An address the OFAC SDN list files under ISIL Khorasan; the case tron-terror-link reaches it.
const LISTED = 'TLDtPq9PQsDuQunME8CSeVdYaLtRdrVgoJ'
const ONLY = process.env.ONLY // only the screens whose name contains this

const browser = await launch({ port: 9339 })
const { page } = browser
const READY = `document.fonts.ready.then(() => document.fonts.check('13px "Public Sans"') && !!document.querySelector('main h1, main [role="alert"]') && !document.querySelector('main [aria-busy="true"]'))`
const GRAPH = `document.querySelectorAll('[role="img"] canvas').length > 0`

try {
  mkdirSync(OUT, { recursive: true })
  const metrics = { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false }
  await page.send('Emulation.setDeviceMetricsOverride', metrics)
  const media = (theme) =>
    page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: 'reduce' }] })
  const save = async (name, theme, full = true) => {
    if (full) {
      const height = await page.evaluate('document.documentElement.scrollHeight')
      await page.send('Emulation.setDeviceMetricsOverride', { ...metrics, height: Math.max(900, height) })
      await sleep(350)
    }
    const { data } = await page.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(join(OUT, `final-${name}-${theme}.png`), Buffer.from(data, 'base64'))
    await page.send('Emulation.setDeviceMetricsOverride', metrics)
    console.log(`final-${name}-${theme}.png`)
  }

  // The app opens light by default; these runs choose the theme through the emulated device.
  await page.send('Page.addScriptToEvaluateOnNewDocument', { source: `try { localStorage.setItem('vaspfusion.theme', 'system') } catch (e) {}` })
  await page.send('Page.navigate', { url: BASE + '/' })
  await waitFor(() => page.evaluate(`!!document.querySelector('h1')`), 'the first screen')
  const api = (method, path, body) =>
    page.evaluate(`fetch(${JSON.stringify(path)}, { method: ${JSON.stringify(method)}, headers: { 'Content-Type': 'application/json' }, body: ${body ? JSON.stringify(JSON.stringify(body)) : 'undefined'} }).then((r) => (r.ok ? r.json() : null))`)
  if ((await api('GET', '/api/auth/me'))?.auth_required) {
    for (const theme of ['light', 'dark']) {
      await media(theme)
      await sleep(400)
      await save('sign-in', theme, false)
    }
    await api('POST', '/api/auth/login', { username: officer.username, password: officer.password })
  }
  const requests = (await api('GET', '/api/requests'))?.items ?? []
  const sent = requests.find((r) => r.status === 'sent') ?? requests[0]
  // A second request, left as a draft, so the pictures show a letter with its watermark too.
  const draft =
    requests.find((r) => r.status === 'drafted') ??
    (await api('POST', '/api/requests', { vasp: 'Bitget', case_ids: ['eth-bitget'], asks: ['kyc', 'transactions'], officer: `${officer.name}, ${officer.post}` }))

  const SHOTS = [
    ['start', '/', undefined, false], // one viewport: the hero is a screen tall, so a full-page capture stretches it
    ['cases', '/cases'],
    ['case-intake', '/cases/new'],
    ['case-attributed', '/cases/tron-coindcx', GRAPH],
    ['case-attributed-wallet', `/cases/tron-coindcx?wallet=TCw8j3nQFnRDMUW2SeNbAgjnVKpELLcoV5`, GRAPH],
    ['case-audit', '/cases/tron-coindcx?tab=audit', GRAPH],
    ['case-wallets', '/cases/tron-abstain?tab=wallets', GRAPH],
    ['case-two-exchanges', '/cases/tron-htx-coindcx', GRAPH],
    ['case-insufficient', '/cases/tron-abstain', GRAPH],
    ['case-sanctioned', '/cases/tron-ofac', GRAPH],
    ['case-bridge', '/cases/eth-bridge', GRAPH],
    ['case-bitcoin', '/cases/btc-htx', GRAPH],
    ['desk', '/desk'],
    ['desk-draft-dialog', '/desk?vasp=HTX&case=btc-htx', `document.querySelectorAll('dialog[open] input[type="checkbox"]').length > 0`, false],
    sent && ['request-sent', `/requests/${sent.id}`, `document.querySelectorAll('.sheet table tbody tr').length > 0`],
    draft && ['request-draft', `/requests/${draft.id}`, `document.querySelectorAll('.sheet table tbody tr').length > 0`],
    ['requests', '/requests'],
    ['exchange', '/vasps/CoinDCX'],
    ['dashboard', '/dashboard'],
    ['labels', '/labels?q=CoinDCX'],
    ['model-tron', '/model'],
    ['model-ethereum', '/model?chain=ethereum'],
    ['watchlist', '/watchlist'],
    ['wallet', `/wallets/tron/${HERO}`],
    // threat tags: a case that reaches listed addresses, a listed wallet, and the two filters
    ['case-threat', '/cases/tron-terror-link', GRAPH],
    ['case-threat-patterns', '/cases/tron-terror-link?tab=patterns', GRAPH],
    ['wallet-threat', `/wallets/tron/${LISTED}`],
    ['labels-threat', '/labels?threat=terrorism_financing'],
    ['cases-threat', '/cases?threat=any'],
  ]
    .filter(Boolean)
    .filter(([name]) => !ONLY || name.includes(ONLY))

  for (const theme of ['light', 'dark']) {
    await media(theme)
    for (const [name, path, ready, full = true] of SHOTS) {
      await page.send('Page.navigate', { url: 'about:blank' })
      await page.send('Page.navigate', { url: BASE + path })
      await waitFor(() => page.evaluate(`${READY}.then((ok) => ok && (${ready ?? 'true'}))`), `${path} to render`)
      await sleep(500)
      await save(name, theme, full)
    }
  }
  void dom
} finally {
  await browser.close()
}
