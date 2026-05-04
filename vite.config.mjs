import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  esbuild: false,
  optimizeDeps: {
    noDiscovery: true,
    include: [],
  },
  server: {
    host: '0.0.0.0',
    port: 1420,
  },
  build: {
    minify: false,
  },
});
