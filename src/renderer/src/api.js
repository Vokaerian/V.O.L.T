// The IPC API exposed by electron/preload.js. Null when the page is opened
// outside Electron (e.g. the Vite URL in a normal browser).
export const api = typeof window !== 'undefined' && window.volt ? window.volt : null;

// One line into volt.log (main.js log:write), for the Steam/SteamCMD/sync
// flows the renderer drives (CLAUDE.md §10). Fire-and-forget, never throws.
export function rlog(message) {
  if (api && api.log) api.log(message).catch(() => {});
}

export function errMsg(err) {
  const msg = err && err.message ? err.message : String(err);
  return msg.replace(/^Error invoking remote method '[^']+': (?:Error: )?/, '');
}
