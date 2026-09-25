// Vite config for the React renderer (renderer/). The Electron main process
// (electron/) is plain CommonJS run directly by Electron and is not bundled.
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: fileURLToPath(new URL('./renderer', import.meta.url)),
  // Relative asset URLs so the built index.html also works when loaded via file://.
  base: './',
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL('./dist/renderer', import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
  },
});
