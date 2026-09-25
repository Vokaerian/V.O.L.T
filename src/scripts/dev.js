'use strict';
// Dev entry point (`npm run dev`): starts the Vite dev server for the
// renderer, then launches Electron against it. Renderer edits hot-reload via
// Vite; edits under electron/ restart the Electron process. Closing the
// Electron window stops the dev server and exits.

const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const SRC = path.resolve(__dirname, '..');

async function main() {
  const { createServer } = await import('vite');
  const server = await createServer({ configFile: path.join(SRC, 'vite.config.mjs') });
  await server.listen();
  server.printUrls();

  const url = server.resolvedUrls && server.resolvedUrls.local && server.resolvedUrls.local[0];
  if (!url) throw new Error('Vite dev server did not report a local URL');

  // Required from plain Node, the electron package exports the path to its binary.
  const electronBin = require('electron');

  let child = null;
  let restarting = false;

  const start = () => {
    const env = { ...process.env, VITE_DEV_SERVER_URL: url };
    delete env.ELECTRON_RUN_AS_NODE;
    child = spawn(electronBin, ['.'], { cwd: SRC, env, stdio: 'inherit' });
    child.on('exit', async (code) => {
      if (restarting) {
        restarting = false;
        start();
        return;
      }
      await server.close();
      process.exit(code ?? 0);
    });
  };

  let timer = null;
  fs.watch(path.join(SRC, 'electron'), { recursive: true }, () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!child || restarting) return;
      console.log('[dev] electron/ changed - restarting Electron...');
      restarting = true;
      child.kill();
    }, 300);
  });

  const stop = () => {
    if (child) child.kill();
    else process.exit(0);
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);

  start();
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
