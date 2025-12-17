/**
 * =============================================================================
 * FILE: vite.config.js
 * LOCATION: /docextract/frontend/vite.config.js
 * =============================================================================
 *
 * PURPOSE:
 *   Vite configuration for the Vue frontend. Configures the dev server,
 *   build output, and proxy settings to connect to the Django backend.
 *
 * PROXY:
 *   /api/* and /admin/* requests are proxied to Django (localhost:8000)
 *   This avoids CORS issues during development.
 *
 * USAGE:
 *   npm run dev    - Start dev server on http://localhost:5173
 *   npm run build  - Build for production to ./dist
 *
 * =============================================================================
 */

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],

  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },

  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/admin': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
      '/media': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },

  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})