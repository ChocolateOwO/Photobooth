import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Build-time instance identity. Anything other than an explicit "main" renders the DUMMY badge.
const instance = process.env.PHOTOBOOTH_INSTANCE === 'main' ? 'main' : 'dummy'
const kioskPort = Number(process.env.PHOTOBOOTH_KIOSK_PORT ?? '8111')
const kioskTarget = `http://127.0.0.1:${kioskPort}`

// Keep the browser's Host header (127.0.0.1:<vite port>): the backend allowlist checks the name.
const proxy = {
  '/api': { target: kioskTarget, changeOrigin: false },
  '/kiosk': { target: kioskTarget, changeOrigin: false },
}

export default defineConfig({
  plugins: [react()],
  define: {
    __PHOTOBOOTH_INSTANCE__: JSON.stringify(instance),
  },
  server: { host: '127.0.0.1', strictPort: true, proxy },
  preview: { host: '127.0.0.1', strictPort: true, proxy },
  build: { outDir: 'dist', sourcemap: false },
})
