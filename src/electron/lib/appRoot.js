'use strict';
// APP-ROOT (SCOPE.md §2a): the folder holding load-orders/, settings.json,
// the log, the community-rules cache and SteamCMD's folders. It's per-game:
// <base>/<GAME_SLUG>, where <base> is resolved as follows.
//  - VOLT_APP_ROOT env var, if set, always wins (testing / custom setups).
//  - Packaged (unpacked-folder build): the folder containing the app's .exe,
//    so the build stays portable - everything lives beside the executable.
//    For a Linux AppImage, the folder containing the .AppImage file.
//  - Dev (`npm run dev`): src/dev-app-root/. In dev, the exe is Electron's own
//    binary inside node_modules, so "folder of the exe" would point there.

const path = require('node:path');

// Active game's APP-ROOT subfolder. Hardcoded to RimWorld (the only game so far)
// until the game-selection screen exists and can pass the real active game in.
const GAME_SLUG = 'rimworld';

function resolveBaseRoot(app, env = process.env) {
  if (env.VOLT_APP_ROOT) return path.resolve(env.VOLT_APP_ROOT);
  if (app.isPackaged) {
    if (env.APPIMAGE) return path.dirname(env.APPIMAGE);
    return path.dirname(app.getPath('exe'));
  }
  return path.join(app.getAppPath(), 'dev-app-root');
}

function resolveAppRoot(app, env = process.env) {
  return path.join(resolveBaseRoot(app, env), GAME_SLUG);
}

module.exports = { resolveAppRoot, resolveBaseRoot, GAME_SLUG };
