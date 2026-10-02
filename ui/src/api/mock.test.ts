import { describe, expect, it } from 'vitest'
import { ApiError, createApi } from './client'
import { createMockTransport } from './mock'

const DEMO_TRON = 'TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR' // mocks/cases/demo-tron-okx.json

/** A mock API whose clock the test moves. */
function mockApi(traceMs = 2000) {
  let now = 1_000_000
  return { api: createApi(createMockTransport({ now: () => now, traceMs })), advance: (ms: number) => (now += ms) }
}

describe('a trace in mock mode', () => {
  it('answers the POST with the case queued, as the live API does', async () => {
    const { api } = mockApi()
    const opened = await api.openCase({ address: DEMO_TRON })
    expect([opened.id, opened.status, opened.outcome, opened.top_vasp, opened.confidence]).toEqual(['demo-tron-okx', 'queued', null, null, null])
  })

  it('reads as queued, then running, with nothing found yet', async () => {
    const { api, advance } = mockApi()
    await api.openCase({ address: DEMO_TRON })
    const queued = await api.case('demo-tron-okx')
    expect(queued.status).toBe('queued')
    advance(1000)
    const running = await api.case('demo-tron-okx')
    expect(running.status).toBe('running')
    expect([running.outcome, running.top_vasp, running.confidence, running.narrative]).toEqual([null, null, null, ''])
    expect([running.hop_rail, running.candidates, running.typology_flags, running.graph.nodes, running.graph.edges]).toEqual([[], [], [], [], []])
    // what the officer entered stays
    expect([running.address, running.chain, running.case_ref]).toEqual([DEMO_TRON, 'tron', 'DEMO/2026/001'])
  })

  it('is the recorded result once the trace time has passed', async () => {
    const { api, advance } = mockApi()
    await api.openCase({ address: DEMO_TRON })
    advance(2000)
    const done = await api.case('demo-tron-okx')
    expect([done.status, done.top_vasp, done.hop_rail.length]).toEqual(['done', 'OKX', 3])
  })

  it('leaves the other cases, and the list, as recorded', async () => {
    const { api } = mockApi()
    await api.openCase({ address: DEMO_TRON })
    expect((await api.case('demo-eth-abstain')).status).toBe('done')
    expect((await api.cases()).items.every((c) => c.status === 'done')).toBe(true)
  })

  it('does not pretend to trace when the trace time is zero', async () => {
    const { api } = mockApi(0)
    expect((await api.openCase({ address: DEMO_TRON })).status).toBe('done')
    expect((await api.case('demo-tron-okx')).status).toBe('done')
  })

  it('still refuses a wallet the fixtures do not hold, and other writes', async () => {
    const { api } = mockApi()
    const unknown = await api.openCase({ address: 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' }).catch((e: unknown) => e)
    expect((unknown as ApiError).status).toBe(422)
    const verify = await api.verifyCase('demo-tron-okx').catch((e: unknown) => e)
    expect((verify as ApiError).status).toBe(501)
  })
})

describe('the audit log in mock mode', () => {
  it('lists only the rows about the case asked for', async () => {
    const { api } = mockApi()
    const all = await api.audit()
    const one = await api.audit({ target: 'demo-tron-okx' })
    expect(all.items.length).toBeGreaterThan(one.items.length)
    expect(one.items.length).toBeGreaterThan(0)
    expect(one.items.every((row) => row.target === 'demo-tron-okx')).toBe(true)
    expect(one.total).toBe(one.items.length)
  })
})
