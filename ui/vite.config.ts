/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => {
  // Where the interface gets its data (src/api/api.ts):
  //   `npm run dev`, tests  → the fixtures in ../mocks, unless VITE_API=live is set
  //   `npm run build`       → the live API, because a built bundle is served by the API itself
  //                           (make serve, the Docker image); VITE_API=mock builds on the fixtures.
  // Set here, not in a .env file: the repo ignores .env.*, so a clean checkout would lose it.
  process.env.VITE_API ??= command === 'build' ? 'live' : 'mock'

  return {
    plugins: [react()],
    // The API and the UI are the same process in production; in dev we proxy so
    // there is no CORS special-casing and no environment-dependent base URL.
    server: {
      // API_PROXY: an API on another port (a second server beside `make serve`).
      proxy: { '/api': process.env.API_PROXY ?? 'http://127.0.0.1:8000' },
      // The mock client reads ../mocks/*.json (the B1 fixtures), one level above ui/.
      fs: { allow: ['..'] },
    },
    build: { outDir: 'dist', chunkSizeWarningLimit: 900 },
    test: {
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      globals: true,
      css: false,
      restoreMocks: true,
    },
  }
})
