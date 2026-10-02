/** The mock transport: `GET /api/<path>` answers with `mocks/<path>.json`, minus the keys
 *  that start with `_` (docs/api_contract.md, "Mocks"). The fixtures are B1's: labelled
 *  addresses in them are real, the suspect wallets and figures are marked demo.
 *
 *  Opening a demo wallet's case behaves as the live API does: the POST answers "queued",
 *  the case then reads queued and running with nothing found yet, and after `traceMs` it is
 *  the recorded result. So the trace screen can be shown, and tested, with no server.
 *
 *  A live build (VITE_API=live) carries none of the fixtures: the glob is compiled out. */
import { ApiError, type Transport } from './client'
import type { AuditPage, CaseDetail, CaseList, CaseSummary } from './models'

const GO_LIVE = 'start the API (make serve) and run the interface with VITE_API=live'

/** How long a demo wallet's trace appears to take, in milliseconds. 0 = the result at once. */
export const mockSettings = { traceMs: 2400 }

const files: Record<string, () => Promise<unknown>> =
  import.meta.env.VITE_API === 'live' ? {} : import.meta.glob('../../../mocks/**/*.json', { import: 'default' })

const loaders = new Map(Object.entries(files).map(([file, load]) => [file.replace(/^.*\/mocks\//, ''), load]))

async function fixture<T>(path: string): Promise<T> {
  const load = loaders.get(`${path.replace(/^\//, '')}.json`)
  if (!load) throw new ApiError(404, `There is no demo fixture for ${path}. To see real data, ${GO_LIVE}.`)
  const raw = (await load()) as Record<string, unknown>
  return Object.fromEntries(Object.entries(raw).filter(([k]) => !k.startsWith('_'))) as T
}

const sameAddress = (a: string, b: string) => (a.startsWith('0x') ? a.toLowerCase() === b.toLowerCase() : a === b)

const NOT_YET = { outcome: null, top_vasp: null, confidence: null } as const

/** A case the trace has not finished: the officer's entries, and nothing found yet. */
function unfinished(c: CaseDetail, status: 'queued' | 'running'): CaseDetail {
  return {
    ...c,
    ...NOT_YET,
    status,
    hop_rail: [],
    graph: { nodes: [], edges: [] },
    candidates: [],
    typology_flags: [],
    where_funds_went: [],
    narrative: '',
    abstain_reason: null,
    what_would_change: [],
    next_steps: [],
  }
}

export function createMockTransport(opts: { now?: () => number; traceMs?: number } = {}): Transport {
  const now = opts.now ?? (() => Date.now())
  const traceMs = () => opts.traceMs ?? mockSettings.traceMs
  /** Case id → when its trace began and how long it takes. */
  const traces = new Map<string, { began: number; ms: number }>()

  const statusOf = (id: string): 'queued' | 'running' | 'done' => {
    const trace = traces.get(id)
    if (!trace) return 'done'
    const elapsed = now() - trace.began
    if (elapsed >= trace.ms) {
      traces.delete(id)
      return 'done'
    }
    return elapsed < trace.ms / 4 ? 'queued' : 'running'
  }

  return {
    async request(method, path, opts = {}) {
      const decoded = decodeURIComponent(path)

      if (method === 'GET') {
        const data = await fixture<unknown>(decoded)
        const caseId = /^\/cases\/([^/]+)$/.exec(decoded)?.[1]
        if (caseId) {
          const status = statusOf(caseId)
          if (status !== 'done') return { data: unfinished(data as CaseDetail, status), source: 'mock' }
        }
        if (decoded === '/audit' && opts.query?.target) {
          const page = data as AuditPage
          const items = page.items.filter((row) => row.target === opts.query!.target)
          return { data: { ...page, items, total: items.length }, source: 'mock' }
        }
        return { data, source: 'mock' }
      }

      if (method === 'POST' && decoded === '/cases') {
        const address = String((opts.body as { address?: unknown } | undefined)?.address ?? '').trim()
        const found = (await fixture<CaseList>('/cases')).items.find((c) => sameAddress(c.address, address))
        if (!found)
          throw new ApiError(
            422,
            `Demo data holds only the ${loaders.has('cases.json') ? 'three ' : ''}demo wallets. To trace any wallet, ${GO_LIVE}.`,
          )
        const ms = traceMs()
        if (ms <= 0) return { data: found, source: 'mock' }
        traces.set(found.id, { began: now(), ms })
        const queued: CaseSummary = { ...found, ...NOT_YET, status: 'queued' }
        return { data: queued, source: 'mock' }
      }

      throw new ApiError(501, `This needs the live API: ${GO_LIVE}.`)
    },
  }
}

export const mockTransport: Transport = createMockTransport()
