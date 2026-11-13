import tailwindcss from '@tailwindcss/vite';
import basicSsl from '@vitejs/plugin-basic-ssl';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// scripts\dev.ps1 -Lan sets ARMS_DEV_LAN=1 (phone testing on the home Wi-Fi, development only):
// - https with a self-signed certificate made on this PC (kept in node_modules/.vite, never in
//   git), so the phone gets a secure context: camera, Web Locks and Secure cookies all work;
// - the proxy adds X-Forwarded-For, so the API sees the phone's address. Uvicorn trusts that
//   header only from 127.0.0.1 (dev.ps1 passes --forwarded-allow-ips 127.0.0.1).
const lan = process.env.ARMS_DEV_LAN === '1';

// The dev server forwards /api to the backend, so the browser talks to one origin,
// exactly as it will behind Caddy in production.
export default defineConfig({
  plugins: [react(), tailwindcss(), ...(lan ? [basicSsl({ name: 'arms-dev-lan' })] : [])],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false, xfwd: lan },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
