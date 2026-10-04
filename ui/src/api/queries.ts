/** TanStack Query hooks over the client. Screens use these, never `fetch`. */
import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { api } from './api'
import { ApiError, getDataSource, subscribeDataSource, type CaseOpen, type CasesQuery, type ComplaintFile, type LabelQuery } from './client'
import type { CaseDetail, Chain, Login, ReplyIn, RequestCreate, RequestPatch, SahyogSim, WatchCreate, WatchList } from './models'

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        staleTime: 15_000,
        // Retry once when the server could not be reached or broke; never on an answer
        // that says no (401, 404, 409, 422): asking again would get the same sentence.
        retry: (failures, error) => failures < 1 && error instanceof ApiError && (error.status === 0 || error.status >= 500),
      },
      mutations: { retry: false },
    },
  })
}

export const keys = {
  me: ['me'] as const,
  health: ['health'] as const,
  cases: (query?: CasesQuery) => ['cases', query ?? {}] as const,
  case: (id: string) => ['case', id] as const,
  audit: (target: string) => ['audit', target] as const,
  labels: (query: LabelQuery) => ['labels', query] as const,
  desk: ['desk'] as const,
  vasp: (name: string) => ['vasp', name] as const,
  requests: ['requests'] as const,
  request: (id: string) => ['request', id] as const,
  dashboard: ['dashboard'] as const,
  model: (chain?: string) => ['model', chain ?? 'tron'] as const,
  wallet: (chain: string, address: string) => ['wallet', chain, address] as const,
  coverage: ['labels', 'coverage'] as const,
  watchlist: ['watchlist'] as const,
  psCoverage: ['ps-coverage'] as const,
  sahyogSim: ['sahyog-sim'] as const,
}

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api.me(), staleTime: 60_000 })

export const useCases = (query?: CasesQuery) => useQuery({ queryKey: keys.cases(query), queryFn: () => api.cases(query) })

const tracing = (c?: CaseDetail) => c?.status === 'queued' || c?.status === 'running'

/** A case's result changes what the list, the dashboard, the desk, an exchange's page and a
 *  wallet's page say: they are read again, not left up to 15 seconds behind. */
function invalidateCaseViews(client: QueryClient) {
  for (const queryKey of [['cases'], keys.dashboard, keys.desk, keys.requests, ['vasp'], ['wallet']])
    void client.invalidateQueries({ queryKey })
}

/** One case. While it is queued or running it is asked for again twice a second, to show its progress. */
export function useCase(id: string) {
  const client = useQueryClient()
  return useQuery({
    queryKey: keys.case(id),
    queryFn: async () => {
      const before = client.getQueryData<CaseDetail>(keys.case(id))
      const now = await api.case(id)
      // The trace ended while this page was asking: the other pages' figures are now old.
      if (tracing(before) && !tracing(now)) invalidateCaseViews(client)
      return now
    },
    refetchInterval: (q) => (tracing(q.state.data) ? 500 : false),
  })
}

export const useLabelSearch = (query: LabelQuery, enabled = true) =>
  useQuery({ queryKey: keys.labels(query), queryFn: () => api.labelSearch(query), enabled })

/** Open a case for a wallet (or get the one it already has). */
export function useOpenCase() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ refresh, ...body }: CaseOpen & { refresh?: boolean }) => api.openCase(body, refresh),
    onSuccess: (opened) => {
      invalidateCaseViews(client)
      // A wallet that already had a case is traced again: drop what was read of it before.
      void client.invalidateQueries({ queryKey: keys.case(opened.id) })
    },
  })
}

/** Who opened, exported or verified one case (the Audit tab). */
export const useAudit = (target: string, enabled = true) =>
  useQuery({ queryKey: keys.audit(target), queryFn: () => api.audit({ target, limit: 100 }), enabled })

/** Trace the wallet again from the cached chain responses and compare with what is stored. */
export function useVerifyCase(id: string) {
  const client = useQueryClient()
  return useMutation({
    mutationFn: () => api.verifyCase(id),
    // Verifying is itself a row in the audit log.
    onSettled: () => client.invalidateQueries({ queryKey: keys.audit(id) }),
  })
}

// --- the request desk ---------------------------------------------------------

export const useDesk = (enabled = true) => useQuery({ queryKey: keys.desk, queryFn: () => api.desk(), enabled })

export const useVasp = (name: string, enabled = true) =>
  useQuery({ queryKey: keys.vasp(name), queryFn: () => api.vasp(name), enabled: enabled && name !== '' })

/** The register: every request, newest first. Filtering is done on the page, so one answer serves every filter. */
export const useRequests = () => useQuery({ queryKey: keys.requests, queryFn: () => api.requests() })

export const useRequest = (id: string) => useQuery({ queryKey: keys.request(id), queryFn: () => api.request(id) })

/** A request changes what the desk, the exchange's page and the register say. */
function useDeskChanged() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: keys.desk })
    void client.invalidateQueries({ queryKey: ['vasp'] })
    void client.invalidateQueries({ queryKey: keys.requests })
    void client.invalidateQueries({ queryKey: keys.dashboard })
  }
}

/** Draft one consolidated request to an exchange. */
export function useDraftRequest() {
  const client = useQueryClient()
  const changed = useDeskChanged()
  return useMutation({
    mutationFn: (body: RequestCreate) => api.createRequest(body),
    onSuccess: (made) => {
      client.setQueryData(keys.request(made.id), made)
      changed()
    },
  })
}

/** Move a request along: approve, send, record the reply, withdraw. */
export function useMoveRequest(id: string) {
  const client = useQueryClient()
  const changed = useDeskChanged()
  return useMutation({
    mutationFn: (body: RequestPatch) => api.patchRequest(id, body),
    onSuccess: (moved) => {
      client.setQueryData(keys.request(id), moved)
      changed()
    },
    // A refusal (409) usually means it changed under the officer: show what is stored now.
    onError: () => void client.invalidateQueries({ queryKey: keys.request(id) }),
  })
}

// --- dashboard, model, wallets, labels, watchlist ------------------------------

/** The rupee reference rate. It is a file on the server: read once. */
export const useFx = () => useQuery({ queryKey: ['fx'] as const, queryFn: () => api.fx(), staleTime: Infinity })
export const useDashboard = () => useQuery({ queryKey: keys.dashboard, queryFn: () => api.dashboard() })

/** `chain`: 'tron' (the model the labels carry) or 'ethereum' (the explorer-tagged benchmark). */
export const useModel = (chain: string) => useQuery({ queryKey: keys.model(chain), queryFn: () => api.model(chain), staleTime: 300_000 })

export const useWallet = (chain: Chain, address: string) =>
  useQuery({ queryKey: keys.wallet(chain, address), queryFn: () => api.wallet(chain, address), enabled: address !== '' })

export const useLabelCoverage = () => useQuery({ queryKey: keys.coverage, queryFn: () => api.labelCoverage(), staleTime: 300_000 })

const checking = (list?: WatchList) => list?.items.some((w) => w.state === 'checking') ?? false

/** Watched wallets. While one is being traced again the list is asked for once a second. */
export const useWatchlist = () =>
  useQuery({ queryKey: keys.watchlist, queryFn: () => api.watchlist(), refetchInterval: (q) => (checking(q.state.data) ? 1000 : false) })

/** A change to the watchlist also changes the dashboard's alerts and a wallet page's "watched". */
function useWatchChanged() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: keys.watchlist })
    void client.invalidateQueries({ queryKey: keys.dashboard })
    void client.invalidateQueries({ queryKey: ['wallet'] })
  }
}

export function useWatch() {
  const changed = useWatchChanged()
  return useMutation({ mutationFn: (body: WatchCreate) => api.watch(body), onSuccess: changed })
}

/** Trace a watched wallet again; its case and the case list change with it. */
export function useCheckWatch() {
  const client = useQueryClient()
  const changed = useWatchChanged()
  return useMutation({
    mutationFn: (id: string) => api.checkWatch(id),
    onSuccess: () => {
      changed()
      void client.invalidateQueries({ queryKey: ['cases'] })
      void client.invalidateQueries({ queryKey: ['case'] })
    },
  })
}

export function useMarkWatchSeen() {
  const changed = useWatchChanged()
  return useMutation({ mutationFn: (id: string) => api.markWatchSeen(id), onSuccess: changed })
}

export function useUnwatch() {
  const changed = useWatchChanged()
  return useMutation({ mutationFn: (id: string) => api.unwatch(id), onSuccess: changed })
}

export function useSignIn() {
  const client = useQueryClient()
  return useMutation({ mutationFn: (body: Login) => api.login(body), onSuccess: () => client.invalidateQueries() })
}

export function useSignOut() {
  const client = useQueryClient()
  return useMutation({ mutationFn: () => api.logout(), onSuccess: () => client.invalidateQueries() })
}

/** The problem statement, line by line. It changes only with a release. */
export const usePsCoverage = () => useQuery({ queryKey: keys.psCoverage, queryFn: () => api.coverage(), staleTime: 300_000 })

const waiting = (sim?: SahyogSim) => sim?.complaints.some((c) => c.status !== 'result') ?? false

/** The simulator's two lists. While a complaint is still being traced it is asked for once a second. */
export const useSahyogSim = () =>
  useQuery({ queryKey: keys.sahyogSim, queryFn: () => api.sahyogSim(), staleTime: 0, refetchInterval: (q) => (waiting(q.state.data) ? 1000 : false) })

/** File a complaint from the simulator: cases appear and are traced, so the case views are read again. */
export function useFileComplaint() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: ComplaintFile) => api.fileComplaint(body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: keys.sahyogSim })
      invalidateCaseViews(client)
    },
  })
}

/** The simulator plays the exchange: the request, the desk and the dashboard change with the reply. */
export function useSimReply() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: ReplyIn & { id: string }) => api.simReply(id, body),
    onSuccess: (_ack, { id }) => {
      for (const queryKey of [keys.sahyogSim, keys.desk, keys.requests, keys.request(id), keys.dashboard, ['vasp']])
        void client.invalidateQueries({ queryKey })
    },
  })
}

/** 'mock' | 'live' | 'mixed' of the latest answer, or null before the first one. */
export const useDataSource = () => useSyncExternalStore(subscribeDataSource, getDataSource, getDataSource)
