import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// /api/* is proxied to the FastAPI app: uvicorn app.main:app --app-dir backend (port 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.LEARGAS_API ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
})
