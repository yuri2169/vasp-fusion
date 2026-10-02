/** The mock transport: `GET /api/<path>` answers with `mocks/<path>.json`, minus the keys
 *  that start with `_` (docs/api_contract.md, "Mocks"). The fixtures are B1's: labelled
 *  addresses in them are real, the suspect wallets and figures are marked demo.
 *
 *  A live build (VITE_API=live) carries none of them: the glob is compiled out. */
import { ApiError, type Transport } from './client'
import type { CaseList } from './models'

const GO_LIVE = 'start the API (make serve) and run the interface with VITE_API=live'

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

export const mockTransport: Transport = {
  async request(method, path, opts = {}) {
    const decoded = decodeURIComponent(path)
    if (method === 'GET') return { data: await fixture(decoded), source: 'mock' }

    if (method === 'POST' && decoded === '/cases') {
      const address = String((opts.body as { address?: unknown } | undefined)?.address ?? '').trim()
      const found = (await fixture<CaseList>('/cases')).items.find((c) => sameAddress(c.address, address))
      if (found) return { data: found, source: 'mock' }
      throw new ApiError(
        422,
        `Demo data holds only the ${loaders.has('cases.json') ? 'three ' : ''}demo wallets. To trace any wallet, ${GO_LIVE}.`,
      )
    }

    throw new ApiError(501, `This needs the live API: ${GO_LIVE}.`)
  },
}
