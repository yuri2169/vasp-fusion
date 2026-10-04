// A Chromium-family browser already on this machine, driven headless over the DevTools protocol.
// Shared by perf.mjs, a11y.mjs and demo-flow.mjs. Nothing is installed or downloaded.
import { spawn } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

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

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export async function waitFor(fn, what, timeoutMs = 20000, everyMs = 100) {
  const deadline = Date.now() + timeoutMs
  let last
  while (Date.now() < deadline) {
    try {
      const v = await fn()
      if (v) return v
    } catch (e) {
      last = e
    }
    await sleep(everyMs)
  }
  throw new Error(`Timed out waiting for ${what}${last ? ` (${last.message})` : ''}`)
}

/** One DevTools-protocol session on one tab: send, evaluate, and listen for events. */
function session(wsUrl) {
  const ws = new WebSocket(wsUrl)
  let next = 1
  const pending = new Map()
  const listeners = new Map()
  ws.addEventListener('message', (e) => {
    const msg = JSON.parse(e.data)
    if (msg.id && pending.has(msg.id)) {
      const { ok, fail } = pending.get(msg.id)
      pending.delete(msg.id)
      if (msg.error) fail(new Error(`${msg.error.message}`))
      else ok(msg.result)
    } else if (msg.method) for (const fn of listeners.get(msg.method) ?? []) fn(msg.params)
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
  const evaluate = async (expression) => {
    const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text)
    return r.result.value
  }
  const on = (method, fn) => listeners.set(method, [...(listeners.get(method) ?? []), fn])
  return { send, evaluate, on, close: () => ws.close() }
}

/** Start the browser with a throwaway profile. `await close()` when done. */
export async function launch({ port = 9335 } = {}) {
  const path = CANDIDATES.find((p) => existsSync(p))
  if (!path) throw new Error('No Chromium-family browser found. Set BROWSER=/path/to/chrome and run again.')
  const profile = mkdtempSync(join(tmpdir(), 'vaspfusion-browser-'))
  const child = spawn(
    path,
    ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--disable-gpu', 'about:blank'],
    { stdio: 'ignore' },
  )
  const targets = await waitFor(async () => (await fetch(`http://127.0.0.1:${port}/json`)).json(), 'the browser to start')
  const page = session(targets.find((t) => t.type === 'page').webSocketDebuggerUrl)
  await page.send('Page.enable')
  await page.send('Runtime.enable')
  return {
    page,
    newTab: async (url) => session((await (await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json()).webSocketDebuggerUrl),
    close: async () => {
      page.close()
      child.kill()
      await sleep(300)
      rmSync(profile, { recursive: true, force: true })
    },
  }
}

/** Helpers every script uses on a page. */
export const dom = {
  clickText: (text, tag = 'button, a, [role="tab"]') =>
    `(() => { const el = [...document.querySelectorAll(${JSON.stringify(tag)})].find((b) => (b.getAttribute('aria-label') ?? b.textContent).trim().startsWith(${JSON.stringify(text)})); if (!el) throw new Error('nothing to click named ' + ${JSON.stringify(text)}); el.click(); return true })()`,
  hasText: (text) => `document.body.innerText.includes(${JSON.stringify(text)})`,
  // Type into an input as React hears it.
  type: (selector, value) =>
    `(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) throw new Error('no field ' + ${JSON.stringify(selector)}); const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event('input', { bubbles: true })); return true })()`,
}
