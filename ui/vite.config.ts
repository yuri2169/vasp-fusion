import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // The API and the UI are the same process in production; in dev we proxy so
  // there is no CORS special-casing and no environment-dependent base URL.
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', chunkSizeWarningLimit: 900 },
})
