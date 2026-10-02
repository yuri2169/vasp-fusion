import { describe, expect, it, vi } from 'vitest'
import { ApiError, createApi, getDataSource, liveTransport, onUnauthorized } from './client'
import { mockTransport } from './mock'

const DEMO_TRON = 'TVZpWtHzwWsD4f9R5BHDRB3y4yskKjUtzR' // mocks/cases/demo-tron-okx.json
const REAL_TRON = 'TYJD2hZKBNrcKW2gYUTV6rJJ2nYie2HP1c' // a real wallet the fixtures do not hold

describe('mock mode (the B1 fixtures in mocks/)', () => {
  const api = createApi(mockTransport)

  it('lists the three demo cases, without the fixture notice keys', async () => {
    const list = await api.cases()
    expect(list.total).toBe(3)
    expect(list.items).toHaveLength(3)
    expect(Object.keys(list).some((k) => k.startsWith('_'))).toBe(false)
    expect(getDataSource()).toBe('mock')
  })

  it('reads one case by id', async () => {
    const c = await api.case('demo-tron-okx')
    expect(c.top_vasp).toBe('OKX')
    expect(c.hop_rail.length).toBeGreaterThan(0)
  })

  it('ignores the query string', async () => {
    expect((await api.model('ethereum')).status).toBeDefined()
    expect((await api.labelSearch({ q: 'coindcx' })).items.length).toBeGreaterThan(0)
  })

  it('answers 404 with a sentence for a path with no fixture', async () => {
    const error = await api.case('nope').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).detail).toMatch(/demo fixture.*VITE_API=live/i)
  })

  it('opens the demo case of a demo wallet', async () => {
    const c = await api.openCase({ address: DEMO_TRON })
    expect(c.id).toBe('demo-tron-okx')
  })

  it('matches an EVM demo wallet whatever its letter case', async () => {
    const eth = (await api.cases()).items.find((c) => c.chain === 'ethereum')!
    expect((await api.openCase({ address: eth.address.toUpperCase().replace('0X', '0x') })).id).toBe(eth.id)
  })

  it('says how to go live when asked to trace any other wallet', async () => {
    const error = await api.openCase({ address: REAL_TRON }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(422)
    expect((error as ApiError).detail).toMatch(/demo data.*VITE_API=live/i)
  })

  it('returns the demo officer', async () => {
    expect((await api.me()).officer?.name).toBeTruthy()
  })

  it('refuses other writes with a sentence', async () => {
    const error = await api.verifyCase('demo-tron-okx').catch((e: unknown) => e)
    expect((error as ApiError).detail).toMatch(/live API/i)
  })
})

describe('live mode', () => {
  const json = (body: unknown, init: ResponseInit = {}) =>
    new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' }, ...init })

  it('fetches /api paths on the same origin, with the session cookie', async () => {
    const fetchMock = vi.fn(async () => json({ total: 0, items: [] }, { headers: { 'X-Data-Source': 'live' } }))
    const api = createApi(liveTransport(fetchMock))
    await api.cases({ outcome: 'ATTRIBUTED' })
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/cases?outcome=ATTRIBUTED')
    expect(init.credentials).toBe('same-origin')
    expect(init.method).toBe('GET')
    expect(getDataSource()).toBe('live')
  })

  it('posts JSON and passes refresh as a query', async () => {
    const fetchMock = vi.fn(async () => json({ id: 'c-0123456789' }, { status: 202 }))
    const api = createApi(liveTransport(fetchMock))
    await api.openCase({ address: REAL_TRON, chain: 'tron' }, true)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/cases?refresh=true')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ address: REAL_TRON, chain: 'tron' })
    expect((init.headers as Record<string, string>)['Content-Type']).toBe('application/json')
  })

  it('records a mixed data source', async () => {
    const api = createApi(liveTransport(async () => json({ total: 0, items: [] }, { headers: { 'X-Data-Source': 'mixed' } })))
    await api.cases()
    expect(getDataSource()).toBe('mixed')
  })

  it("turns the server's sentence into an ApiError", async () => {
    const api = createApi(liveTransport(async () => json({ detail: 'A draft cannot be sent. Approve it first.' }, { status: 409 })))
    const error = await api.patchRequest('req-1', { status: 'sent' }).catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 409, detail: 'A draft cannot be sent. Approve it first.' })
    expect((error as Error).message).toBe('A draft cannot be sent. Approve it first.')
  })

  it('joins a validation list into one sentence', async () => {
    const detail = [{ loc: ['body', 'address'], msg: 'Field required', type: 'missing' }]
    const api = createApi(liveTransport(async () => json({ detail }, { status: 422 })))
    const error = await api.openCase({ address: '' }).catch((e: unknown) => e)
    expect((error as ApiError).detail).toBe('The server refused the request: address: Field required.')
  })

  it('says what to do when the server cannot be reached', async () => {
    const api = createApi(liveTransport(async () => { throw new TypeError('Failed to fetch') }))
    const error = await api.cases().catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 0 })
    expect((error as ApiError).detail).toMatch(/cannot reach the VASP-FUSION server/i)
  })

  it('gives a plain sentence for an error with no JSON body', async () => {
    const api = createApi(liveTransport(async () => new Response('Bad Gateway', { status: 502 })))
    const error = await api.cases().catch((e: unknown) => e)
    expect((error as ApiError).detail).toMatch(/502/)
  })

  it('tells listeners about a 401, but not one from the login form itself', async () => {
    const seen = vi.fn()
    const off = onUnauthorized(seen)
    const api = createApi(liveTransport(async () => json({ detail: 'Sign in to continue.' }, { status: 401 })))
    await api.cases().catch(() => {})
    expect(seen).toHaveBeenCalledTimes(1)
    await api.login({ username: 'a', password: 'b' }).catch(() => {})
    expect(seen).toHaveBeenCalledTimes(1)
    off()
  })

  it('builds the PDF links', () => {
    const api = createApi(liveTransport(async () => json({})))
    expect(api.caseFileUrl('tron-coindcx')).toBe('/api/cases/tron-coindcx/pdf')
    expect(api.requestPdfUrl('req-2026-0001')).toBe('/api/requests/req-2026-0001/pdf')
  })
})
