// The 3-minute demo, driven end to end in a real browser, against the running tool
// (the offline Docker image: `UI=build make docker && make docker-up`, or `make serve`).
//
//   node scripts/demo-flow.mjs                     BASE_URL=http://127.0.0.1:8000 by default
//   FRAMES=/some/dir node scripts/demo-flow.mjs    also keeps what the screen showed, for the recording
//   PACE=0 node scripts/demo-flow.mjs              no pauses (a check, not a recording)
//
// Every step asserts what is on the screen; the script exits 1 at the first thing that is not
// there. It signs in with the published demonstration account (demo/officer.json) when the
// server asks for a login. Three cases, in the order the jury sees them:
//   1. a recorded Tron wallet is traced while watched -> CoinDCX -> "Why CoinDCX?" -> a request is
//      drafted, approved, marked as sent -> the letter PDF -> the desk -> the dashboard's count moved;
//   2. a wallet where the evidence is not enough: no exchange is named, and no request is offered;
//   3. a wallet that paid a sanctioned address.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { dom, launch, sleep, waitFor } from './browser.mjs'

const BASE = process.env.BASE_URL ?? 'http://127.0.0.1:8000'
const FRAMES = process.env.FRAMES
const PACE = Number(process.env.PACE ?? 1)
const THEME = process.env.THEME ?? 'light'
const here = dirname(fileURLToPath(import.meta.url))
const officer = JSON.parse(readFileSync(resolve(here, '..', '..', 'demo', 'officer.json'), 'utf8'))
const HERO = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' // demo/cases.json: tron-coindcx

const browser = await launch({ port: 9338 })
const { page } = browser
let step = 0
const frames = []
const pause = (ms) => sleep(ms * PACE)
const say = (text) => console.log(`${String(++step).padStart(2)}. ${text}`)
const text = () => page.evaluate('document.body.innerText')
const path = () => page.evaluate('location.pathname + location.search')
const see = (needle, what = needle, timeoutMs = 20000) => waitFor(() => page.evaluate(dom.hasText(needle)), `"${what}" on the screen`, timeoutMs)
const click = (name, tag) => page.evaluate(dom.clickText(name, tag))
const inDialog = (name) => click(name, 'dialog[open] button')
const expect = (cond, what) => {
  if (!cond) throw new Error(`Not as expected: ${what}`)
}
const shot = async (name) => {
  if (!FRAMES) return
  const { data } = await page.send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(FRAMES, `still-${String(step).padStart(2, '0')}-${name}.png`), Buffer.from(data, 'base64'))
}
const count = async (name) =>
  page.evaluate(`(() => { const li = [...document.querySelectorAll('ul[aria-label="Counts"] li')].find((x) => x.innerText.toLowerCase().startsWith(${JSON.stringify(name.toLowerCase())})); return li ? Number(li.querySelector('.font-mono').innerText.replace(/,/g, '')) : null })()`)

try {
  await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })
  await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: THEME === 'dark' ? 'dark' : 'light' }] })
  if (FRAMES) {
    mkdirSync(FRAMES, { recursive: true })
    page.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
      const file = `frame-${String(frames.length).padStart(5, '0')}.jpg`
      writeFileSync(join(FRAMES, file), Buffer.from(data, 'base64'))
      frames.push({ file, t: metadata.timestamp, step })
      void page.send('Page.screencastFrameAck', { sessionId })
    })
    await page.send('Page.startScreencast', { format: 'jpeg', quality: 80, maxWidth: 1440, maxHeight: 900, everyNthFrame: 2 })
  }

  // --- sign in --------------------------------------------------------------------------------
  await page.send('Page.navigate', { url: BASE + '/' })
  await waitFor(() => page.evaluate(`!!document.querySelector('h1')`), 'the first screen')
  if ((await text()).includes('Sign in to VASP-FUSION')) {
    say('The tool asks who is using it: every case and request is logged under a name')
    await shot('sign-in')
    await pause(1200)
    await page.evaluate(dom.type('input[autocomplete="username"]', officer.username))
    await page.evaluate(dom.type('input[autocomplete="current-password"]', officer.password))
    await pause(600)
    await click('Sign in', 'button[type="submit"]')
    await see('Open a case', 'the list of cases after signing in')
    expect((await text()).includes(officer.name), `the rail names the officer signed in (${officer.name})`)
  } else say('This server asks for no login (VASPFUSION_AUTH=off, or no officer account)')

  // --- how fast the first screen is -------------------------------------------------------------
  await page.send('Page.navigate', { url: BASE + '/cases' })
  await waitFor(() => page.evaluate(`document.querySelectorAll('tbody tr [data-testid="outcome-stamp"]').length > 0`), 'the list of cases')
  const loadMs = await page.evaluate('performance.now()')
  say(`The list of cases is on screen ${Math.round(loadMs)} ms after the page was asked for`)
  expect(loadMs < 2000, `the first screen loads in under 2 s (took ${Math.round(loadMs)} ms)`)
  expect(!(await text()).includes('demo data'), 'nothing on screen is a fixture: no "demo data" tag')
  await pause(1500)

  // --- the dashboard before -------------------------------------------------------------------
  await click('Dashboard', 'nav a')
  await waitFor(() => count('Awaiting a reply').then((n) => n !== null), 'the dashboard counts')
  const before = { awaiting: await count('Awaiting a reply'), toWrite: await count('Exchanges to write to') }
  say(`Dashboard before: ${before.awaiting} request(s) awaiting a reply, ${before.toWrite} exchange(s) to write to`)
  await pause(1500)

  // --- case 1: trace a recorded Tron wallet, watched --------------------------------------------
  await click('Cases', 'nav a')
  await see('Open a case')
  await click('Open a case', 'main a')
  await waitFor(() => page.evaluate(`!!document.querySelector('form[aria-label="Open a case"] input')`), 'the intake sheet')
  await pause(800)
  await page.evaluate(dom.type('form[aria-label="Open a case"] input', HERO))
  await see('TRON', 'the chain named while the address is typed')
  say('A Tron wallet is pasted: the sheet names the chain before anything is traced')
  await pause(1000)
  await page.evaluate(`document.querySelector('form[aria-label="Open a case"] input[type="checkbox"]').click()`)
  await pause(500)
  await shot('intake')
  await click('Trace wallet', 'form[aria-label="Open a case"] button[type="submit"]')
  await waitFor(async () => (await path()).startsWith('/cases/tron-coindcx'), 'the case page')
  await waitFor(() => page.evaluate(`document.querySelector('[aria-label="Path of the funds"] [data-testid="outcome-stamp"]')?.getAttribute('data-outcome') === 'ATTRIBUTED'`), 'the Hop Rail ending in the stamp')
  // A wallet that already has a case keeps its previous answer on screen until the new trace is in.
  await see('Trace finished', 'the line that says the trace finished and what it read')
  say('The trace runs from recorded chain responses (no network) and the Hop Rail extends to the stamp')
  await pause(2500)
  await see('Why CoinDCX?')
  const page1 = await text()
  expect(/0\.85/.test(page1), 'CoinDCX is named at 0.85')
  expect(page1.includes('Holds without its strongest label'), 'the counterfactual is on the page')
  await waitFor(() => page.evaluate(`document.querySelectorAll('[role="img"] canvas').length > 0`), 'the fund-flow graph')
  say('"Why CoinDCX?": 0.85, the evidence in sentences, and the answer holds without its strongest label')
  await shot('case-coindcx')
  await pause(3500)

  // --- draft, approve, send ---------------------------------------------------------------------
  await click('Draft request to CoinDCX', 'main a')
  await waitFor(() => page.evaluate(`document.querySelectorAll('dialog[open] input[type="checkbox"]').length >= 5`), 'the draft dialog with its case and the four asks')
  // Signed in, the officer's line is filled in; a server with no login leaves it to be typed.
  if (await page.evaluate(`document.querySelector('dialog[open] input:not([type="checkbox"])').value === ''`))
    await page.evaluate(dom.type('dialog[open] input:not([type="checkbox"])', `${officer.name}, ${officer.post}`))
  expect(await page.evaluate(`[...document.querySelectorAll('dialog[open] input[type="checkbox"]')].filter((b) => b.checked).length >= 5`), 'the case and the four asks are ticked')
  await pause(1800)
  await shot('draft-dialog')
  await inDialog('Draft request')
  await waitFor(async () => (await path()).startsWith('/requests/'), 'the letter')
  await see('Request drafted', 'the toast "Request drafted"')
  const requestPath = await path()
  await waitFor(() => page.evaluate(`document.querySelector('.sheet')?.getAttribute('data-draft') === 'true'`), 'the draft letter with its watermark')
  say(`A request to CoinDCX is drafted (${requestPath}): an A4 letter, watermarked until approved`)
  await shot('letter-draft')
  await pause(3000)
  await click('Approve request', 'aside button')
  await waitFor(() => page.evaluate(`!!document.querySelector('dialog[open]')`), 'the approve dialog')
  await pause(1200)
  await inDialog('Approve request')
  await see('Request approved', 'the toast "Request approved"')
  await waitFor(() => page.evaluate(`document.querySelector('.sheet')?.getAttribute('data-draft') === 'false'`), 'the watermark gone')
  await pause(1800)
  await click('Mark as sent', 'aside button')
  await waitFor(() => page.evaluate(`!!document.querySelector('dialog[open]')`), 'the send dialog')
  await pause(1200)
  await inDialog('Mark as sent')
  await see('Marked as sent', 'the toast "Marked as sent"')
  await see('nothing left this machine', 'the receipt says the gateway is a local outbox')
  say('Approved, then marked as sent: the toast repeats each verb, and the receipt says nothing left this machine')
  await shot('letter-sent')
  await pause(2500)

  // --- the letter PDF -------------------------------------------------------------------------
  const pdf = await page.evaluate(`fetch(document.querySelector('aside a[href*="/pdf"]').getAttribute('href')).then(async (r) => ({ status: r.status, type: r.headers.get('content-type'), head: new TextDecoder().decode((await r.arrayBuffer()).slice(0, 5)), size: Number(r.headers.get('content-length')) }))`)
  expect(pdf.status === 200 && pdf.type === 'application/pdf' && pdf.head === '%PDF-', `the letter PDF is served (${JSON.stringify(pdf)})`)
  say(`"Open letter PDF" gives the A4 letter (${pdf.type}, ${pdf.size} bytes): the file that was handed to the gateway`)

  // --- the desk shows it, the dashboard moved ---------------------------------------------------
  await click('Request desk', 'nav a')
  await waitFor(() => page.evaluate(`[...document.querySelectorAll('tbody tr')].some((tr) => tr.innerText.includes('CoinDCX') && /sent/i.test(tr.querySelector('[data-testid="status-tag"]')?.innerText ?? ''))`), 'the desk row of CoinDCX reading "Sent"')
  say('The request desk shows CoinDCX as sent, with the day a reply is due')
  await shot('desk')
  await pause(2500)
  await click('Dashboard', 'nav a')
  await waitFor(() => count('Awaiting a reply').then((n) => n === before.awaiting + 1), `"Awaiting a reply" going from ${before.awaiting} to ${before.awaiting + 1}`)
  say(`Dashboard after: ${await count('Awaiting a reply')} awaiting a reply (was ${before.awaiting})`)
  await shot('dashboard')
  await pause(2500)

  // --- back on the case: it now leads to its request, not to a second draft --------------------
  await page.evaluate(`history.pushState({}, '', '/cases/tron-coindcx'); dispatchEvent(new PopStateEvent('popstate'))`)
  await see('Open request to CoinDCX', 'the case page leading to its request')
  expect(!/Draft request to CoinDCX/.test(await text()), 'no second draft is offered for a case already in a request')
  say('The case now leads to its request ("Open request to CoinDCX", Sent) instead of offering a second draft')
  await pause(2000)

  // --- case 2: not enough evidence --------------------------------------------------------------
  await page.evaluate(`history.pushState({}, '', '/cases/tron-abstain'); dispatchEvent(new PopStateEvent('popstate'))`)
  await see('No exchange is named')
  await waitFor(() => page.evaluate(`document.querySelector('[aria-label="Path of the funds"] [data-testid="outcome-stamp"]')?.getAttribute('data-outcome') === 'INSUFFICIENT_EVIDENCE'`), 'the INSUFFICIENT EVIDENCE stamp')
  const page2 = await text()
  expect(!/Draft request to/.test(page2), 'no request is offered when no exchange is named')
  expect(page2.includes('What would change this'), 'the page says what would change the answer')
  say('Second case: INSUFFICIENT EVIDENCE. No exchange is named, no request is offered, and the page says what would change that')
  await shot('case-abstain')
  await pause(4000)

  // --- case 3: a sanctioned address -------------------------------------------------------------
  await page.evaluate(`history.pushState({}, '', '/cases/tron-ofac'); dispatchEvent(new PopStateEvent('popstate'))`)
  await waitFor(() => page.evaluate(`document.querySelector('[aria-label="Path of the funds"] [data-testid="outcome-stamp"]')?.getAttribute('data-outcome') === 'SANCTIONED_OR_MIXER_REACHED'`), 'the SANCTIONED stamp')
  const page3 = await text()
  expect(/OFAC/i.test(page3), 'the sanctions list is named')
  say('Third case: the funds went straight to an OFAC-listed address; the alert leads the page')
  await shot('case-sanctioned')
  await pause(4000)

  if (FRAMES) {
    await page.send('Page.stopScreencast')
    writeFileSync(join(FRAMES, 'frames.json'), JSON.stringify(frames))
    console.log(`\n${frames.length} frames in ${FRAMES}`)
  }
  console.log(`\nPASS: the demo flow ran start to finish (${step} steps) against ${BASE}`)
} catch (e) {
  console.error(`\nFAIL at step ${step}: ${e.message}\n  on ${await path().catch(() => '?')}`)
  if (FRAMES) await shot('failure').catch(() => {})
  process.exitCode = 1
} finally {
  await browser.close()
}
