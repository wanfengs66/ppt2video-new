import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:9002',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:9002',
        changeOrigin: true,
      },
      '/files': {
        target: 'http://localhost:9002',
        changeOrigin: true,
      },
      '/output_videos': {
        target: 'http://localhost:9002',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../backend/static/frontend',
    emptyOutDir: true,
  },
})
