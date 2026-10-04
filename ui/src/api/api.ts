import { createApi, liveTransport, type Transport } from './client'

/** 'live' talks to the real API on this origin; anything else reads the fixtures in mocks/.
 *  `npm run dev` is mock unless VITE_API=live is set; a build is live (vite.config.ts). */
export const API_MODE: 'mock' | 'live' = import.meta.env.VITE_API === 'live' ? 'live' : 'mock'

/** The fixture transport, fetched on its first use. A live build never reaches this branch, so
 *  it carries neither the fixtures nor the code that serves them (scripts/check-bundle.mjs). */
const fixtures: Transport = {
  request: async (method, path, opts) => (await import('./mock')).mockTransport.request(method, path, opts),
}

export const api = createApi(import.meta.env.VITE_API === 'live' ? liveTransport() : fixtures)
