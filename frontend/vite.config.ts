import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react') || id.includes('node_modules/react-router') || id.includes('node_modules/react-is')) {
            return 'vendor-react';
          }
          if (id.includes('node_modules/mermaid') || id.includes('node_modules/@mermaid-js')) {
            return 'vendor-mermaid';
          }
          if (id.includes('node_modules/bpmn-js') || id.includes('node_modules/@bpmn-io') || id.includes('node_modules/bpmn-moddle') || id.includes('node_modules/camunda-bpmn-moddle') || id.includes('node_modules/diagram-js')) {
            return 'vendor-bpmn';
          }
          if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-geo') || id.includes('node_modules/react-simple-maps')) {
            return 'vendor-charts';
          }
          if (id.includes('node_modules/shiki') || id.includes('node_modules/@shikijs')) {
            return 'vendor-shiki';
          }
          if (id.includes('node_modules/jspdf') || id.includes('node_modules/html-to-image') || id.includes('node_modules/docx') || id.includes('node_modules/html2canvas')) {
            return 'vendor-pdf';
          }
          if (id.includes('node_modules/@projectstorm')) {
            return 'vendor-diagrams';
          }
        },
      },
    },
  },
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: {
      '@assets': path.resolve(__dirname, 'attached_assets'),
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      'react/jsx-runtime': path.resolve(__dirname, 'node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': path.resolve(__dirname, 'node_modules/react/jsx-dev-runtime.js'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5000,
    allowedHosts: true,
    proxy: process.env.VITE_API_URL ? undefined : {
      '/api/admin/workflows/execute-stream': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        headers: {
          'Connection': 'keep-alive',
        },
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            proxyRes.headers['cache-control'] = 'no-cache';
            proxyRes.headers['x-accel-buffering'] = 'no';
          });
        },
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
