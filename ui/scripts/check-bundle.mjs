// After `npm run build`: a live bundle must carry no fixture and no fixture transport, the
// graph library must be in a chunk of its own, the 3D library in another that only the 3D
// view asks for, and what the first paint loads must stay small.
//
//   node scripts/check-bundle.mjs            (run by `make ui-build`)
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const dist = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
const html = readFileSync(join(dist, 'index.html'), 'utf8')
const assets = readdirSync(join(dist, 'assets')).filter((f) => f.endsWith('.js'))
const read = (f) => readFileSync(join(dist, 'assets', f), 'utf8')
const fail = []

// Strings that exist only in src/api/mock.ts and in mocks/*.json.
const FIXTURE_MARKS = ['There is no demo fixture for', 'vaspfusion-demo:', 'demo-tron-okx', '"_demo"']
for (const f of assets) for (const mark of FIXTURE_MARKS) if (read(f).includes(mark)) fail.push(`${f} carries fixture code or data (${mark})`)

const entry = [...html.matchAll(/(?:src|href)="\/assets\/([^"]+\.js)"/g)].map((m) => m[1])
const first = entry.reduce((n, f) => n + gzipSync(read(f)).length, 0)
const BUDGET = 200 * 1024
if (entry.some((f) => /cytoscape/i.test(read(f).slice(0, 4000)) || read(f).includes('userZoomingEnabled')))
  fail.push('the graph library is in the first load: FlowGraph must stay React.lazy')
if (first > BUDGET) fail.push(`the first load is ${(first / 1024).toFixed(0)} KB gzipped, over the ${BUDGET / 1024} KB budget`)

// The 3D view (three.js): in the build, so the offline tool has it, and in no chunk that
// loads before 3D is chosen. `WebGLRenderer` is three's own; the 2D graph has no use for it.
const is3d = (f) => read(f).includes('WebGLRenderer')
const kb = (f) => `${(statSync(join(dist, 'assets', f)).size / 1024).toFixed(0)} KB (${(gzipSync(read(f)).length / 1024).toFixed(0)} KB gzipped)`
const three = assets.filter(is3d)
const graph = assets.find((f) => read(f).includes('userZoomingEnabled'))
if (three.length === 0) fail.push('the 3D view is not in the build: the offline tool could not show it')
if (entry.some(is3d)) fail.push('the 3D library is in the first load: Flow3D must stay React.lazy')
if (graph && is3d(graph)) fail.push('the 3D library is in the 2D graph chunk: it must load only when 3D is chosen')
// every script the page names up front, the ones it preloads included
const upfront = [...html.matchAll(/\/assets\/([^"]+\.js)/g)].map((m) => m[1])
if (upfront.some(is3d)) fail.push('the 3D library is preloaded by the page')
if (graph) console.log(`2D graph chunk: ${graph} = ${kb(graph)}`)
for (const f of three) console.log(`3D chunk, loaded only when 3D is chosen: ${f} = ${kb(f)}`)

const total = assets.reduce((n, f) => n + statSync(join(dist, 'assets', f)).size, 0)
console.log(`first load: ${entry.join(', ')} = ${(first / 1024).toFixed(0)} KB gzipped; all scripts: ${(total / 1024).toFixed(0)} KB in ${assets.length} files`)
if (fail.length) {
  for (const line of fail) console.error(`FAIL: ${line}`)
  process.exit(1)
}
console.log('PASS: no fixture in the bundle, the graph and the 3D view load on demand, the first load is within budget.')
