import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(['/api', '/ask', '/health', '/nodes', '/node', '/edges', '/graph', '/path', '/exports']
      .map(path => [path, { target: 'http://127.0.0.1:8079', changeOrigin: true }])),
  },
})
