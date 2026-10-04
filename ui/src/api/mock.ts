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
import { CHAINS } from '../lib/chains'
import { detectChain, validate } from '../lib/addresses'
import type { AuditPage, CaseDetail, CaseList, CaseProgress, CaseSummary, Chain, Desk, RequestDetail, RequestList, RequestStatus, WalletDetail, WatchItem } from './models'

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

const count = (n: number, word: string) => `${n.toLocaleString('en-US')} ${word}${n === 1 ? '' : 's'}`

/** What the trace of a demo wallet would have read by `done` (0 to 1 of its run), worked out
 *  from the fixture's own graph: hop by hop out, then the funders, then the check of the
 *  result. The sentence has the form the live API writes (vaspfusion/explain/progress.py). */
function progressAt(c: CaseDetail, done: number): CaseProgress | null {
  if (done < 0.15) return null // queued: nothing read yet
  const hops = Math.max(1, ...c.graph.nodes.map((n) => n.hop))
  const phase = done < 0.75 ? 'outbound' : done < 0.85 ? 'inbound' : 'checking'
  const hop = phase === 'outbound' ? Math.min(hops, 1 + Math.floor(((done - 0.15) / 0.6) * hops)) : hops
  const hopOf = new Map(c.graph.nodes.map((n) => [n.id, n.hop]))
  const wallets = c.graph.nodes.filter((n) => n.hop < hop).length
  const transfers = c.graph.edges.filter((e) => (hopOf.get(e.source) ?? 0) < hop).length
  const asset = c.asset ?? c.hop_rail[0]?.asset ?? c.graph.edges[0]?.asset ?? null
  const reached: CaseProgress['reached'] = []
  for (const n of [...c.graph.nodes].sort((a, b) => a.hop - b.hop))
    if (n.label && n.hop <= hop && !reached.some((r) => r.entity === n.label!.entity))
      reached.push({ entity: n.label.entity, category: n.label.category, hop: n.hop })

  const where = CHAINS[c.chain].name
  const read = `${transfers.toLocaleString('en-US')} ${asset ? `${asset} ` : ''}transfer${transfers === 1 ? '' : 's'} of ${count(wallets, 'wallet')}`
  const plain = (r: (typeof reached)[number]) => ['exchange', 'custodial_wallet', 'swap_service'].includes(r.category)
  const names = reached.map((r) => (plain(r) ? r.entity : `${r.entity} (${r.category})`)).join(', ')
  const soFar = (lead: string) => (names ? ` ${lead}: ${names}.` : '')
  const message =
    phase === 'outbound'
      ? `Following the money on ${where}: ${read} read, ${count(hop, 'hop')} out.${soFar('Reached so far')}`
      : phase === 'inbound'
        ? `Followed the money ${count(hop, 'hop')} out on ${where} (${read}). Now reading who funded the wallet.${soFar('Reached so far')}`
        : `Read ${read} on ${where}. Now checking the result: each exchange that would be named is traced again without its label.${soFar('Reached')}`
  return { phase, asset, hop, wallets_read: wallets, transfers_read: transfers, reached, message }
}

/** A case the trace has not finished: the officer's entries, what has been read so far, and nothing found yet. */
function unfinished(c: CaseDetail, status: 'queued' | 'running', done: number): CaseDetail {
  return {
    ...c,
    ...NOT_YET,
    status,
    progress: progressAt(c, done),
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

/** Which status a request may move to from where it is (vaspfusion/desk/service.py, TRANSITIONS). */
const TRANSITIONS: Record<RequestStatus, RequestStatus[]> = {
  drafted: ['approved', 'withdrawn'],
  approved: ['sent', 'drafted', 'withdrawn'],
  sent: ['acknowledged', 'answered', 'freeze_confirmed', 'refused'],
  acknowledged: ['answered', 'freeze_confirmed', 'refused'],
  answered: ['freeze_confirmed'],
  freeze_confirmed: [],
  refused: [],
  withdrawn: [],
}
const AWAITING: RequestStatus[] = ['sent', 'acknowledged']

export function createMockTransport(opts: { now?: () => number; traceMs?: number } = {}): Transport {
  const now = opts.now ?? (() => Date.now())
  const traceMs = () => opts.traceMs ?? mockSettings.traceMs
  /** Case id → when its trace began and how long it takes. */
  const traces = new Map<string, { began: number; ms: number }>()

  /** How far the trace of a case has got, 0 to 1; null once it is done (or was never started). */
  const doneOf = (id: string): number | null => {
    const trace = traces.get(id)
    if (!trace) return null
    const elapsed = now() - trace.began
    if (elapsed >= trace.ms) {
      traces.delete(id)
      return null
    }
    return elapsed / trace.ms
  }

  /** The demo request as the officer has moved it in this session (the live API stores it; nothing here does). */
  const moved = new Map<string, RequestDetail>()
  const requestNow = async (id: string) => moved.get(id) ?? (await fixture<RequestDetail>(`/requests/${id}`))

  /** Wallets the officer watches in this session. Demo data cannot trace, so a wallet here is
   *  compared with nothing: a demo wallet reads "no change", any other "not traced yet". */
  const watched = new Map<string, WatchItem>()
  async function watchItem(chain: Chain, address: string, note: string | null): Promise<WatchItem> {
    const found = (await fixture<CaseList>('/cases')).items.find((c) => c.chain === chain && sameAddress(c.address, address))
    const at = new Date(now()).toISOString()
    return {
      id: `${chain}-${address}`,
      chain,
      address,
      note,
      added_at: at,
      added_by: null,
      case_id: found?.id ?? null,
      state: found ? 'unchanged' : 'not_traced',
      last_checked_at: found?.created_at ?? null,
      baseline_at: found?.created_at ?? null,
      changes: [],
      error: null,
      label: null,
    }
  }

  return {
    async request(method, path, opts = {}) {
      const decoded = decodeURIComponent(path)
      const requestId = /^\/requests\/([^/]+)$/.exec(decoded)?.[1]
      const watchId = /^\/watchlist\/([^/]+)(?:\/(check|seen))?$/.exec(decoded)

      if (decoded === '/watchlist' && method === 'GET') return { data: { items: [...watched.values()].reverse() }, source: 'mock' }
      if (decoded === '/watchlist' && method === 'POST') {
        const body = (opts.body ?? {}) as { address?: string; chain?: Chain | null; note?: string | null }
        const address = String(body.address ?? '').trim()
        const chain = body.chain ?? detectChain(address)
        if (!chain || !validate(address, chain))
          throw new ApiError(422, 'Could not tell which chain this address is on. Pick the chain and try again.')
        const item = await watchItem(chain, address, body.note?.trim() || null)
        if (watched.has(item.id)) throw new ApiError(409, 'This wallet is already on the watchlist.')
        watched.set(item.id, item)
        return { data: item, source: 'mock' }
      }
      if (watchId) {
        const item = watched.get(watchId[1])
        if (!item) throw new ApiError(404, 'This wallet is not on the watchlist.')
        if (method === 'DELETE') {
          watched.delete(item.id)
          return { data: { ok: true }, source: 'mock' }
        }
        if (watchId[2] === 'seen' && item.case_id) return { data: item, source: 'mock' }
        throw new ApiError(501, `Demo data cannot trace a wallet again. To check a watched wallet, ${GO_LIVE}.`)
      }
      const walletOf = /^\/wallets\/([^/]+)\/([^/]+)$/.exec(decoded)
      if (method === 'GET' && walletOf) {
        const [, chain, address] = walletOf
        const known = loaders.has(`wallets/${chain}/${address}.json`)
        const cases = (await fixture<CaseList>('/cases')).items.filter((c) => c.chain === chain && sameAddress(c.address, address))
        const wallet: WalletDetail = known
          ? await fixture<WalletDetail>(decoded)
          : {
              address,
              chain: chain as Chain,
              labels: [],
              risk: { score: null, level: null, reasons: [] },
              cases: cases.map((c) => ({ case_id: c.id, role: 'suspect', hop: 0 })),
              inbound: null,
              outbound: null,
              flows_from_cases: 0,
              watched: false,
            }
        return { data: { ...wallet, watched: watched.has(`${chain}-${address}`) }, source: 'mock' }
      }

      if (method === 'GET' && requestId) return { data: await requestNow(requestId), source: 'mock' }
      if (method === 'GET' && decoded === '/requests') {
        const list = await fixture<RequestList>('/requests')
        const { vasp, status } = opts.query ?? {}
        const items = list.items
          .map((r) => moved.get(r.id) ?? r)
          .filter((r) => (!vasp || r.vasp.toLowerCase() === String(vasp).toLowerCase()) && (!status || r.status === status))
        return { data: { items }, source: 'mock' }
      }
      if (method === 'GET' && decoded === '/desk' && moved.size > 0) {
        const desk = await fixture<Desk>('/desk')
        const now_ = (id: string | null | undefined) => (id ? moved.get(id) : undefined)
        return {
          data: {
            follow_ups: desk.follow_ups.filter((f) => AWAITING.includes(now_(f.request_id)?.status ?? 'sent')),
            rows: desk.rows.map((row) => ({ ...row, status: now_(row.last_request_id)?.status ?? row.status })),
          },
          source: 'mock',
        }
      }

      if (method === 'POST' && decoded === '/requests') {
        const vasp = String((opts.body as { vasp?: unknown } | undefined)?.vasp ?? '')
        const found = (await fixture<RequestList>('/requests')).items.find((r) => r.vasp.toLowerCase() === vasp.toLowerCase())
        if (!found) throw new ApiError(404, `Demo data holds no request to ${vasp}. To draft one from a traced case, ${GO_LIVE}.`)
        return { data: moved.get(found.id) ?? found, source: 'mock' }
      }

      if (method === 'PATCH' && requestId) {
        const req = await requestNow(requestId)
        const { status, note } = (opts.body ?? {}) as { status: RequestStatus; note?: string | null }
        if (!TRANSITIONS[req.status].includes(status))
          throw new ApiError(409, `A request that is ${req.status} cannot become ${status}.`)
        const next: RequestDetail = {
          ...req,
          status,
          allowed_next: TRANSITIONS[status],
          status_history: [...req.status_history, { status, at: new Date(now()).toISOString(), note: note ?? null, by: null }],
        }
        moved.set(requestId, next)
        return { data: next, source: 'mock' }
      }

      if (method === 'GET') {
        const data = await fixture<unknown>(decoded)
        const caseId = /^\/cases\/([^/]+)$/.exec(decoded)?.[1]
        if (caseId) {
          const done = doneOf(caseId)
          if (done !== null) return { data: unfinished(data as CaseDetail, done < 0.15 ? 'queued' : 'running', done), source: 'mock' }
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
        if (ms <= 0) {
          traces.delete(found.id)
          return { data: found, source: 'mock' }
        }
        traces.set(found.id, { began: now(), ms })
        const queued: CaseSummary = { ...found, ...NOT_YET, status: 'queued' }
        return { data: queued, source: 'mock' }
      }

      throw new ApiError(501, `This needs the live API: ${GO_LIVE}.`)
    },
  }
}

export const mockTransport: Transport = createMockTransport()
