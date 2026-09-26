'use strict';
// APP-ROOT (SCOPE.md §2a): the folder holding load-orders/, settings.json,
// the log, the community-rules cache and (RimWorld only) SteamCMD's
// folders. It's per-game: <base>/<slug>, where <base> is resolved as
// follows and <slug> is the game the user picked on the game-selection
// screen (main.js's game:activate IPC) — exactly one game is activated
// per process lifetime, since there's no way back to the game-select
// screen once one is chosen.
//  - VOLT_APP_ROOT env var, if set, always wins (testing / custom setups).
//  - Packaged (unpacked-folder build): the folder containing the app's .exe,
//    so the build stays portable - everything lives beside the executable.
//    For a Linux AppImage, the folder containing the .AppImage file.
//  - Dev (`npm run dev`): src/dev-app-root/. In dev, the exe is Electron's own
//    binary inside node_modules, so "folder of the exe" would point there.

const path = require('node:path');

// RimWorld's own slug. steam.js's short-lived helper process (the only place
// outside main.js/game:activate that resolves an APP-ROOT directly) uses
// this rather than a raw string literal, since steam.js only ever runs for
// RimWorld.
const GAME_SLUG = 'rimworld';

function resolveBaseRoot(app, env = process.env) {
  if (env.VOLT_APP_ROOT) return path.resolve(env.VOLT_APP_ROOT);
  if (app.isPackaged) {
    if (env.APPIMAGE) return path.dirname(env.APPIMAGE);
    return path.dirname(app.getPath('exe'));
  }
  return path.join(app.getAppPath(), 'dev-app-root');
}

function resolveAppRoot(app, slug, env = process.env) {
  return path.join(resolveBaseRoot(app, env), slug);
}

module.exports = { resolveAppRoot, resolveBaseRoot, GAME_SLUG };
