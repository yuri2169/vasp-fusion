import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { api } from './api'
import type { CaseDetail, CaseSummary } from './models'
import { createQueryClient, keys, useCase, useOpenCase } from './queries'

function setup() {
  const client = createQueryClient()
  const invalidated: unknown[] = []
  const real = client.invalidateQueries.bind(client)
  vi.spyOn(client, 'invalidateQueries').mockImplementation((filters, options) => {
    invalidated.push(filters?.queryKey)
    return real(filters, options)
  })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return { client, invalidated, wrapper }
}

const OTHER_VIEWS = [['cases'], keys.dashboard, keys.desk, keys.requests, ['vasp'], ['wallet']]

describe('what a trace changes on the other pages', () => {
  it('reads the list, dashboard, desk, exchange and wallet pages again when a watched trace ends', async () => {
    const { client, invalidated, wrapper } = setup()
    client.setQueryData(keys.case('c-1'), { id: 'c-1', status: 'running' } as CaseDetail)
    vi.spyOn(api, 'case').mockResolvedValue({ id: 'c-1', status: 'done' } as CaseDetail)
    const { result } = renderHook(() => useCase('c-1'), { wrapper })
    await waitFor(() => expect(result.current.data?.status).toBe('done'))
    expect(invalidated).toEqual(expect.arrayContaining(OTHER_VIEWS))
  })

  it('leaves them alone when a finished case is only read', async () => {
    const { invalidated, wrapper } = setup()
    vi.spyOn(api, 'case').mockResolvedValue({ id: 'c-1', status: 'done' } as CaseDetail)
    const { result } = renderHook(() => useCase('c-1'), { wrapper })
    await waitFor(() => expect(result.current.data?.status).toBe('done'))
    expect(invalidated).toEqual([])
  })

  it('reads them again when a case is opened', async () => {
    const { invalidated, wrapper } = setup()
    vi.spyOn(api, 'openCase').mockResolvedValue({ id: 'c-2', status: 'queued' } as CaseSummary)
    const { result } = renderHook(() => useOpenCase(), { wrapper })
    result.current.mutate({ address: 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(invalidated).toEqual(expect.arrayContaining([...OTHER_VIEWS, keys.case('c-2')]))
  })
})
