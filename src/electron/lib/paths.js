'use strict';
// Path autodetection (SCOPE.md §2): find the RimWorld install root for Steam
// or GOG, plus the game's config folder (ModsConfig.xml). Both storefronts use
// the same <install root>/Mods layout, so this only branches to *find* the root.

const os = require('node:os');
const path = require('node:path');
const { parseVdf, getCI } = require('./vdf');
const { readRegValue, readRegTree } = require('./registry');
const { exists, isDir, readText, findChildCI } = require('./fsutil');

const STEAM_APPID = '294100';
const GOG_GAME_ID = '1094900708'; // RimWorld's GOG product id; the gameName match is the primary check.
const GAME_EXES = ['RimWorldWin64.exe', 'RimWorldWin.exe', 'RimWorldLinux', 'RimWorldMac.app'];

// Registry values sometimes use forward slashes (Steam's SteamPath does).
function norm(p) {
  return p ? path.normalize(process.platform === 'win32' ? p.replace(/\//g, '\\') : p) : p;
}

function dedupe(list) {
  const seen = new Set();
  const out = [];
  for (const p of list) {
    if (!p) continue;
    const key = process.platform === 'win32' ? p.toLowerCase() : p;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(p);
  }
  return out;
}

async function isGameRoot(dir) {
  if (!(await isDir(dir))) return false;
  if (await isDir(path.join(dir, 'Data', 'Core'))) return true;
  for (const exe of GAME_EXES) if (await exists(path.join(dir, exe))) return true;
  return false;
}

// Accepts the install root, or its Mods/Data folder picked by mistake.
async function normalizeGameDir(dir) {
  if (!dir) return null;
  const d = path.resolve(dir);
  if (await isGameRoot(d)) return d;
  const parent = path.dirname(d);
  if (parent !== d && ['mods', 'data'].includes(path.basename(d).toLowerCase()) && (await isGameRoot(parent))) {
    return parent;
  }
  return null;
}

async function steamRootCandidates() {
  const c = [];
  const home = os.homedir();
  if (process.platform === 'win32') {
    c.push(await readRegValue('HKCU\\Software\\Valve\\Steam', 'SteamPath'));
    c.push(await readRegValue('HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam', 'InstallPath'));
    c.push(await readRegValue('HKLM\\SOFTWARE\\Valve\\Steam', 'InstallPath'));
    c.push('C:\\Program Files (x86)\\Steam', 'C:\\Program Files\\Steam');
  } else if (process.platform === 'linux') {
    c.push(
      path.join(home, '.steam', 'steam'),
      path.join(home, '.local', 'share', 'Steam'),
      path.join(home, '.var', 'app', 'com.valvesoftware.Steam', '.local', 'share', 'Steam'),
    );
  } else if (process.platform === 'darwin') {
    c.push(path.join(home, 'Library', 'Application Support', 'Steam'));
  }
  return dedupe(c.map(norm));
}

// Library folders from libraryfolders.vdf. hasApp: true/false when the file
// lists installed app ids (newer format), null when unknown (older format).
async function steamLibraries(steamRoot) {
  const libs = [{ path: steamRoot, hasApp: null }];
  for (const rel of [['steamapps', 'libraryfolders.vdf'], ['config', 'libraryfolders.vdf']]) {
    let data;
    try {
      data = parseVdf(await readText(path.join(steamRoot, ...rel)));
    } catch {
      continue;
    }
    const root = getCI(data, 'libraryfolders');
    if (!root || typeof root !== 'object') continue;
    for (const [k, v] of Object.entries(root)) {
      if (!/^\d+$/.test(k)) continue;
      const p = typeof v === 'string' ? v : getCI(v, 'path');
      if (!p) continue;
      const apps = typeof v === 'object' ? getCI(v, 'apps') : null;
      const hasApp = apps && typeof apps === 'object' ? Object.prototype.hasOwnProperty.call(apps, STEAM_APPID) : null;
      libs.push({ path: norm(p), hasApp });
    }
  }
  // Same library can appear twice (root + entry "0"); keep the most informative.
  const byKey = new Map();
  for (const lib of libs) {
    const key = process.platform === 'win32' ? lib.path.toLowerCase() : lib.path;
    const prev = byKey.get(key);
    if (!prev || (prev.hasApp == null && lib.hasApp != null)) byKey.set(key, lib);
  }
  return [...byKey.values()];
}

async function findSteamInstall(tried) {
  for (const steamRoot of await steamRootCandidates()) {
    if (!(await isDir(steamRoot))) continue;
    const libs = await steamLibraries(steamRoot);
    const ordered = [...libs.filter((l) => l.hasApp === true), ...libs.filter((l) => l.hasApp !== true)];
    for (const lib of ordered) {
      const steamapps = path.join(lib.path, 'steamapps');
      let installdir = 'RimWorld';
      try {
        const acf = parseVdf(await readText(path.join(steamapps, `appmanifest_${STEAM_APPID}.acf`)));
        const d = getCI(getCI(acf, 'AppState'), 'installdir');
        if (typeof d === 'string' && d) installdir = d;
      } catch {
        // No manifest in this library - still try the default folder name.
      }
      const candidate = path.join(steamapps, 'common', installdir);
      tried.push(candidate);
      if (await isGameRoot(candidate)) {
        return { source: 'steam', gameDir: candidate, steamRoot, workshopDir: workshopDirFor(candidate) };
      }
    }
  }
  return null;
}

async function findGogInstall(tried) {
  const candidates = [];
  const home = os.homedir();
  if (process.platform === 'win32') {
    for (const key of ['HKLM\\SOFTWARE\\WOW6432Node\\GOG.com\\Games', 'HKLM\\SOFTWARE\\GOG.com\\Games']) {
      for (const b of await readRegTree(key)) {
        const v = b.values;
        const isRimWorld =
          /rimworld/i.test(v.gamename || '') ||
          /rimworld/i.test(v.exe || '') ||
          b.key.toLowerCase().endsWith(`\\games\\${GOG_GAME_ID}`);
        if (isRimWorld && v.path) candidates.push(norm(v.path));
      }
    }
    candidates.push('C:\\GOG Games\\RimWorld', 'C:\\Program Files (x86)\\GOG Galaxy\\Games\\RimWorld');
  } else if (process.platform === 'linux') {
    candidates.push(path.join(home, 'GOG Games', 'RimWorld', 'game'), path.join(home, 'GOG Games', 'RimWorld'));
  }
  for (const c of dedupe(candidates)) {
    tried.push(c);
    const gameDir = await normalizeGameDir(c);
    if (gameDir) return { source: 'gog', gameDir };
  }
  return null;
}

// RimWorld's config folder (holds ModsConfig.xml). Same for Steam and GOG.
function defaultConfigDir() {
  const home = os.homedir();
  const sub = ['Ludeon Studios', 'RimWorld by Ludeon Studios', 'Config'];
  if (process.platform === 'win32') return path.join(home, 'AppData', 'LocalLow', ...sub);
  if (process.platform === 'linux') return path.join(home, '.config', 'unity3d', ...sub);
  if (process.platform === 'darwin') return path.join(home, 'Library', 'Application Support', 'RimWorld', 'Config');
  return null;
}

// Runs every detector. `game` is the pick (Steam preferred), `games` all hits.
async function autodetect() {
  const tried = [];
  const steam = await findSteamInstall(tried);
  const gog = await findGogInstall(tried);
  const games = [steam, gog].filter(Boolean);
  const cfg = defaultConfigDir();
  return {
    game: games[0] || null,
    games,
    configDir: cfg && (await isDir(cfg)) ? cfg : null,
    tried,
  };
}

// Steam layout: <library>/steamapps/common/<installdir> -> <library>/steamapps/workshop/content/294100.
// Derived from gameDir rather than stored, so it can't go stale in settings.json.
function workshopDirFor(gameDir) {
  return path.join(gameDir, '..', '..', 'workshop', 'content', STEAM_APPID);
}

// Steam-integrated builds ship steam_appid.txt in the install folder; GOG
// builds don't. Gates both Workshop-folder scanning (modRoots) and the
// Steamworks client (lib/steam.js) - checked on disk, not via gameSource, so
// a manually-Browsed Steam install still counts (SCOPE.md §2).
async function hasSteamAppId(gameDir) {
  return !!(gameDir && (await findChildCI(gameDir, 'steam_appid.txt')));
}

// Folders scanned for mods, in priority order (earlier wins on a duplicate
// packageId): Core/DLC in <game>/Data (required - the game won't start
// without Core), local <game>/Mods, then Steam Workshop content when the
// install ships steam_appid.txt (a Steam build, however gameDir was picked;
// GOG has neither). A missing Workshop folder is skipped. SteamCMD downloads
// are copied into Mods (lib/steamCmd.js), so they need no root of their own.
async function modRoots(gameDir) {
  const roots = [
    { dir: path.join(gameDir, 'Data'), source: 'official' },
    { dir: path.join(gameDir, 'Mods'), source: 'local' },
  ];
  if (await hasSteamAppId(gameDir)) {
    const ws = workshopDirFor(gameDir);
    if (await isDir(ws)) roots.push({ dir: ws, source: 'workshop' });
  }
  return roots;
}

async function readGameVersion(gameDir) {
  try {
    const first = (await readText(path.join(gameDir, 'Version.txt'))).split(/\r?\n/)[0].trim();
    return first || null;
  } catch {
    return null;
  }
}

module.exports = {
  STEAM_APPID,
  GAME_EXES,
  isGameRoot,
  normalizeGameDir,
  defaultConfigDir,
  autodetect,
  readGameVersion,
  steamLibraries,
  workshopDirFor,
  hasSteamAppId,
  modRoots,
};
