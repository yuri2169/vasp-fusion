// Scratch shooter: node scripts/_shoot.mjs <outDir> <theme> <width> name=path ...
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { launch, sleep, waitFor } from './browser.mjs'
const [out, theme, width, ...shots] = process.argv.slice(2)
const BASE = process.env.BASE_URL ?? 'http://localhost:5183'
mkdirSync(out, { recursive: true })
const browser = await launch({ port: 9341 })
try {
  const page = await browser.newTab('about:blank')
  await page.send('Emulation.setDeviceMetricsOverride', { width: Number(width), height: 900, deviceScaleFactor: 1, mobile: false })
  await page.send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: 'reduce' }] })
  for (const shot of shots) {
    const [name, path] = shot.split('=')
    await page.send('Page.navigate', { url: 'about:blank' })
    await page.send('Page.navigate', { url: BASE + path })
    await waitFor(() => page.evaluate(`document.fonts.ready.then(() => !!document.querySelector('main h1, main h2'))`), path)
    await sleep(Number(process.env.WAIT ?? 1500))
    const { cssContentSize: s } = await page.send('Page.getLayoutMetrics')
    const full = process.env.FOLD ? 900 : Math.min(Math.ceil(s.height), 4200)
    const { data } = await page.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: Number(width), height: full, scale: 1 } })
    writeFileSync(join(out, `${name}-${theme}.png`), Buffer.from(data, 'base64'))
    console.log(name, s.height)
  }
} finally { await browser.close() }
