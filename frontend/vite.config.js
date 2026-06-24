import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('/@antv/') || id.includes('/@ant-design/plots')) {
            return 'vendor-antv'
          }
          if (id.includes('/echarts') || id.includes('/zrender')) {
            return 'vendor-echarts'
          }
          return undefined
        },
      },
    },
  },
  server: {
    port: 3601,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
})
