/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // The API and the UI are the same process in production; in dev we proxy so
  // there is no CORS special-casing and no environment-dependent base URL.
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
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
})
