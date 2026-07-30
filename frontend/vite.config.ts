import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        // === SSE 流式代理关键配置 ===
        // 关键：仅移除 content-encoding 防止 gzip 缓冲 SSE 流。
        // 不要调用 res.flushHeaders() — 那会与 http-proxy 默认的 writeHead 冲突，
        // 导致 Content-Type 等头部被清空。
        configure: (proxy) => {
          proxy.on('proxyRes', (_proxyRes) => {
            const ct = _proxyRes.headers['content-type'] || '';
            if (ct.includes('text/event-stream')) {
              delete _proxyRes.headers['content-encoding'];
            }
          });
        },
      },
    },
  },
})
