/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Прокси /api (включая WebSocket) на ядро; сборка в dist, его отдаёт ядро.
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      // React Flow — отдельный файл: общий бандл иначе больше 500 КБ (предупреждение сборки)
      output: {
        codeSplitting: { groups: [{ name: 'xyflow', test: /node_modules[\\/]@xyflow[\\/]/ }] },
      },
      // Предупреждение стороннего react-compiler-runtime («use no memo») безвредно.
      onLog(level, log, handler) {
        const id = String(log.id ?? log.loc?.file ?? '')
        if (log.code === 'MODULE_LEVEL_DIRECTIVE' && id.includes('react-compiler-runtime')) return
        handler(level, log)
      },
    },
  },
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', ws: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
