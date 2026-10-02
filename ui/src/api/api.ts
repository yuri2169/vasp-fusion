import { createApi, liveTransport } from './client'
import { mockTransport } from './mock'

/** 'live' talks to the real API on this origin; anything else reads the fixtures in mocks/.
 *  `npm run dev` is mock unless VITE_API=live is set; a build is live (.env.production). */
export const API_MODE: 'mock' | 'live' = import.meta.env.VITE_API === 'live' ? 'live' : 'mock'

export const api = createApi(API_MODE === 'live' ? liveTransport() : mockTransport)
