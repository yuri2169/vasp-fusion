/** The one way the interface talks to VASP-FUSION. See docs/api_contract.md.
 *
 *  Two transports behind the same typed functions:
 *    mock  the B1 fixtures in mocks/ (the default in `npm run dev` and in tests)
 *    live  the real API on the same origin (VITE_API=live; the default in a build)
 */
import type {
  AuditPage,
  CaseCreate,
  CaseDetail,
  CaseList,
  CaseSummary,
  Chain,
  Dashboard,
  DataSource,
  Desk,
  Health,
  LabelCoverage,
  LabelSearch,
  Login,
  LoginResult,
  Me,
  ModelInfo,
  Ok,
  Receipt,
  RequestCreate,
  RequestDetail,
  RequestList,
  RequestPatch,
  RequestStatus,
  VaspDetail,
  VerifyResult,
  WalletDetail,
  WatchCreate,
  WatchItem,
  WatchList,
} from './models'

/** An error the officer can read: `detail` is the server's sentence (what happened, what to do). */
export class ApiError extends Error {
  readonly status: number
  readonly detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export type Query = Record<string, string | number | boolean | null | undefined>

export type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

export interface Transport {
  request(method: Method, path: string, opts?: { query?: Query; body?: unknown }): Promise<{
    data: unknown
    source: DataSource | null
  }>
}

// --- what the screen shows about where the data came from ------------------

let dataSource: DataSource | null = null
const sourceListeners = new Set<() => void>()

/** The `X-Data-Source` of the latest answer: anything but 'live' gets a "Demo data" tag. */
export const getDataSource = (): DataSource | null => dataSource
export function subscribeDataSource(fn: () => void): () => void {
  sourceListeners.add(fn)
  return () => sourceListeners.delete(fn)
}
function recordSource(source: DataSource | null) {
  if (!source || source === dataSource) return
  dataSource = source
  for (const fn of sourceListeners) fn()
}

const unauthorizedListeners = new Set<() => void>()
/** Called when any route answers 401 "Sign in to continue." (the shell then shows sign-in). */
export function onUnauthorized(fn: () => void): () => void {
  unauthorizedListeners.add(fn)
  return () => unauthorizedListeners.delete(fn)
}

// --- live transport --------------------------------------------------------

function queryString(query?: Query): string {
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
  const s = params.toString()
  return s ? `?${s}` : ''
}

function sentence(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    // Pydantic: [{loc: ['body', 'address'], msg: 'Field required'}]
    const parts = detail.map((d: { loc?: unknown[]; msg?: string }) => {
      const field = (d.loc ?? []).filter((p) => p !== 'body' && p !== 'query' && p !== 'path').join('.')
      return field ? `${field}: ${d.msg}` : String(d.msg)
    })
    return `The server refused the request: ${parts.join('; ')}.`
  }
  return `VASP-FUSION could not finish this (error ${status}). Nothing was changed. Try again; if it keeps happening, tell whoever runs this installation.`
}

export function liveTransport(fetchImpl: typeof fetch = (...args) => fetch(...args)): Transport {
  return {
    async request(method, path, opts = {}) {
      const headers: Record<string, string> = { Accept: 'application/json' }
      if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
      let response: Response
      try {
        response = await fetchImpl(`/api${path}${queryString(opts.query)}`, {
          method,
          headers,
          credentials: 'same-origin',
          body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        })
      } catch {
        throw new ApiError(0, 'Cannot reach the VASP-FUSION server. Check that it is running, then try again.')
      }
      const body: unknown = await response.json().catch(() => null)
      if (!response.ok) {
        if (response.status === 401 && path !== '/auth/login') for (const fn of unauthorizedListeners) fn()
        throw new ApiError(response.status, sentence(response.status, body))
      }
      const source = response.headers.get('X-Data-Source')
      return { data: body, source: source === 'mock' || source === 'live' || source === 'mixed' ? source : null }
    },
  }
}

// --- the typed surface -----------------------------------------------------

/** What the officer has to give to open a case; the rest has server defaults. */
export type CaseOpen = Pick<CaseCreate, 'address'> & Partial<Omit<CaseCreate, 'address'>>
export type CasesQuery = { outcome?: CaseSummary['outcome']; status?: CaseSummary['status'] }
export type LabelQuery = { q?: string; chain?: string; category?: string; tier?: string; limit?: number; offset?: number }
export type RequestsQuery = { vasp?: string; status?: RequestStatus }
export type AuditQuery = { limit?: number; offset?: number; officer?: string; action?: string; target?: string; verify?: boolean }

const seg = encodeURIComponent

export function createApi(transport: Transport) {
  async function call<T>(method: Method, path: string, opts?: { query?: Query; body?: unknown }): Promise<T> {
    const { data, source } = await transport.request(method, path, opts)
    recordSource(source)
    return data as T
  }
  const get = <T>(path: string, query?: Query) => call<T>('GET', path, { query })

  return {
    health: () => get<Health>('/health'),

    me: () => get<Me>('/auth/me'),
    login: (body: Login) => call<LoginResult>('POST', '/auth/login', { body }),
    logout: () => call<Ok>('POST', '/auth/logout'),

    cases: (query?: CasesQuery) => get<CaseList>('/cases', query),
    case: (id: string) => get<CaseDetail>(`/cases/${seg(id)}`),
    /** Answers at once with a queued case; poll `case(id)` until it is done or failed. */
    openCase: (body: CaseOpen, refresh = false) =>
      call<CaseSummary>('POST', '/cases', { body, query: refresh ? { refresh: true } : undefined }),
    receipt: (id: string) => get<Receipt>(`/cases/${seg(id)}/receipt`),
    verifyCase: (id: string) => call<VerifyResult>('POST', `/cases/${seg(id)}/verify`),
    caseFileUrl: (id: string) => `/api/cases/${seg(id)}/pdf`,

    wallet: (chain: Chain, address: string) => get<WalletDetail>(`/wallets/${seg(chain)}/${seg(address)}`),
    labelSearch: (query: LabelQuery) => get<LabelSearch>('/labels/search', query),
    /** How many labels the store holds, by chain, category, tier and source. */
    labelCoverage: () => get<LabelCoverage>('/labels/coverage'),

    watchlist: () => get<WatchList>('/watchlist'),
    watch: (body: WatchCreate) => call<WatchItem>('POST', '/watchlist', { body }),
    /** Traces the wallet again; the item reads `checking` until that is done. */
    checkWatch: (id: string) => call<WatchItem>('POST', `/watchlist/${seg(id)}/check`),
    markWatchSeen: (id: string) => call<WatchItem>('POST', `/watchlist/${seg(id)}/seen`),
    unwatch: (id: string) => call<Ok>('DELETE', `/watchlist/${seg(id)}`),

    desk: () => get<Desk>('/desk'),
    vasp: (name: string) => get<VaspDetail>(`/vasps/${seg(name)}`),
    /** The register: every request, newest first, withdrawn ones included. */
    requests: (query?: RequestsQuery) => get<RequestList>('/requests', query),
    request: (id: string) => get<RequestDetail>(`/requests/${seg(id)}`),
    createRequest: (body: RequestCreate) => call<RequestDetail>('POST', '/requests', { body }),
    patchRequest: (id: string, body: RequestPatch) => call<RequestDetail>('PATCH', `/requests/${seg(id)}`, { body }),
    requestPdfUrl: (id: string) => `/api/requests/${seg(id)}/pdf`,

    dashboard: () => get<Dashboard>('/dashboard'),
    /** `chain`: 'tron' (the default) or 'ethereum'. */
    model: (chain?: string) => get<ModelInfo>('/model', { chain }),
    audit: (query?: AuditQuery) => get<AuditPage>('/audit', query),
  }
}

export type Api = ReturnType<typeof createApi>
