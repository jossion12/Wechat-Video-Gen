import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 后端不再挂载 /uploads、/outputs 静态目录;
      // 所有素材与产物都通过 /api/files/{id} 和 /api/jobs/{id}/output 取(带所有权校验)。
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});