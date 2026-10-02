/** TanStack Query hooks over the client. Screens use these, never `fetch`. */
import { QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { api } from './api'
import { ApiError, getDataSource, subscribeDataSource, type CaseOpen, type CasesQuery, type LabelQuery } from './client'
import type { CaseDetail } from './models'

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
  labels: (query: LabelQuery) => ['labels', query] as const,
  desk: ['desk'] as const,
  dashboard: ['dashboard'] as const,
  model: (chain?: string) => ['model', chain ?? 'tron'] as const,
}

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: api.me, staleTime: 60_000 })

export const useCases = (query?: CasesQuery) => useQuery({ queryKey: keys.cases(query), queryFn: () => api.cases(query) })

const tracing = (c?: CaseDetail) => c?.status === 'queued' || c?.status === 'running'

/** One case. While it is queued or running it is asked for again every second. */
export const useCase = (id: string) =>
  useQuery({
    queryKey: keys.case(id),
    queryFn: () => api.case(id),
    refetchInterval: (q) => (tracing(q.state.data) ? 1000 : false),
  })

export const useLabelSearch = (query: LabelQuery, enabled = true) =>
  useQuery({ queryKey: keys.labels(query), queryFn: () => api.labelSearch(query), enabled })

/** Open a case for a wallet (or get the one it already has). */
export function useOpenCase() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ refresh, ...body }: CaseOpen & { refresh?: boolean }) => api.openCase(body, refresh),
    onSuccess: () => client.invalidateQueries({ queryKey: ['cases'] }),
  })
}

export function useSignIn() {
  const client = useQueryClient()
  return useMutation({ mutationFn: api.login, onSuccess: () => client.invalidateQueries() })
}

export function useSignOut() {
  const client = useQueryClient()
  return useMutation({ mutationFn: api.logout, onSuccess: () => client.invalidateQueries() })
}

/** 'mock' | 'live' | 'mixed' of the latest answer, or null before the first one. */
export const useDataSource = () => useSyncExternalStore(subscribeDataSource, getDataSource, getDataSource)
