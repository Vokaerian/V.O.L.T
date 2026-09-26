'use strict';
// Electron main process. Owns all filesystem/registry access; the renderer
// talks to it only through the IPC API exposed in preload.js.

const fs = require('node:fs/promises');
const path = require('node:path');
const { app, BrowserWindow, clipboard, dialog, ipcMain, shell } = require('electron');
const { resolveAppRoot, resolveBaseRoot } = require('./lib/appRoot');
const { createSettingsStore } = require('./lib/settings');
const { createWindowStateStore } = require('./lib/windowState');
const paths = require('./lib/paths');
const { isDir, exists, writeFileAtomic, removeTreeBestEffort } = require('./lib/fsutil');
const { scanModRoots, readPreviewDataUrl } = require('./lib/mods');
const modsConfig = require('./lib/modsConfig');
const loadOrders = require('./lib/loadOrders');
const communityRules = require('./lib/communityRules');
const modListIO = require('./lib/modListIO');
const steam = require('./lib/steam');
const steamWebApi = require('./lib/steamWebApi');
const steamCmd = require('./lib/steamCmd');
const { isWritableId, cleanIds } = require('./lib/ids');
const { initLog, log, clip, ipcArgsText, ipcResultText } = require('./lib/log');

const windowState = createWindowStateStore(resolveBaseRoot(app));
// Resolved once the renderer activates a game (game:activate IPC, below) -
// exactly one game is chosen per process lifetime (App.jsx's GameGate has
// no way back to game-select), so these never need to support switching.
let appRoot = null;
let settings = null;
let logPath = null;

// Get whatever is about to crash the main process into the log first, no
// recovery. 'uncaughtExceptionMonitor' fires before Node/Electron's default
// handling without replacing it (a plain 'uncaughtException' listener would
// suppress Electron's error dialog / crash). An 'unhandledRejection' listener
// does replace the default warning, so it's echoed to the console as well.
const errText = (e) => (e instanceof Error ? e.stack || e.message : String(e));
process.on('uncaughtExceptionMonitor', (err, origin) => log(`${origin}: ${errText(err)}`));
process.on('unhandledRejection', (reason) => {
  log(`unhandledRejection: ${errText(reason)}`);
  console.error('[volt] unhandledRejection:', reason);
});
let mainWindow = null;

// IPC handlers return { ok, value } / { ok: false, error } so the renderer gets
// clean error messages (preload.js unwraps them). Every call is logged with its
// arguments and its result or error (lib/log.js ipcArgsText / ipcResultText:
// clipboard / pasted text as its length only).
function handle(channel, fn) {
  ipcMain.handle(channel, async (_event, ...args) => {
    log(`ipc ${channel} ${ipcArgsText(channel, args)}`);
    try {
      const value = await fn(...args);
      log(`ipc ${channel} ok: ${ipcResultText(channel, value)}`);
      return { ok: true, value };
    } catch (err) {
      console.error(`[ipc ${channel}]`, err);
      log(`ipc ${channel} failed: ${err && err.message ? err.message : String(err)}`);
      return { ok: false, error: err && err.message ? err.message : String(err) };
    }
  });
}

// Current paths, validated against disk.
async function pathsState() {
  const s = await settings.get();
  const gameOk = s.gameDir ? await paths.isGameRoot(s.gameDir) : false;
  const configOk = s.configDir ? await isDir(s.configDir) : false;
  return {
    gameDir: gameOk ? s.gameDir : null,
    gameSource: gameOk ? s.gameSource : null,
    savedGameDirMissing: !!s.gameDir && !gameOk,
    modsDir: gameOk ? path.join(s.gameDir, 'Mods') : null,
    configDir: configOk ? s.configDir : null,
    modsConfigPath: configOk ? modsConfig.modsConfigPath(s.configDir) : null,
    gameVersion: gameOk ? await paths.readGameVersion(s.gameDir) : null,
  };
}

// Autodetect and store results. `force` overwrites paths that are already set.
async function runAutodetect(force) {
  const found = await paths.autodetect();
  const state = await pathsState();
  const patch = {};
  if (found.game && (force || !state.gameDir)) {
    patch.gameDir = found.game.gameDir;
    patch.gameSource = found.game.source;
  }
  if (found.configDir && (force || !state.configDir)) patch.configDir = found.configDir;
  if (Object.keys(patch).length) await settings.update(patch);
  return {
    game: found.game ? { source: found.game.source, gameDir: found.game.gameDir } : null,
    gamesFound: found.games.length,
    configDir: found.configDir,
  };
}

// Called once, right after the user picks a game on the game-select screen
// (game:activate IPC below). Resolves that game's real APP-ROOT and
// (re)creates its settings store and log. Never needs to tear down a
// previous activation - see the comment on the `let appRoot` declaration.
function activateGame(slug) {
  appRoot = resolveAppRoot(app, slug);
  settings = createSettingsStore(appRoot);
  logPath = initLog(appRoot);
  console.log(`[volt] activated '${slug}' - APP-ROOT: ${appRoot}`);
  return { slug, appRoot };
}

function registerIpc() {
  handle('game:activate', async (slug) => activateGame(slug));
  handle('app:info', async () => ({
    version: app.getVersion(),
    appRoot,
    logPath,
    // volt.log.prev: the previous run's log (log.js rotation), if there is one.
    prevLogPath: (await exists(`${logPath}.prev`)) ? `${logPath}.prev` : null,
    isPackaged: app.isPackaged,
    platform: process.platform,
  }));

  handle('settings:get', () => settings.get());

  // Renderer-side log lines (api.js rlog): the Steam/SteamCMD/sync flows the
  // renderer drives. Not through handle(), which would log each line twice.
  ipcMain.handle('log:write', (_event, message) => {
    log(`[renderer] ${clip(String(message))}`);
    return { ok: true };
  });

  // First call of a session fills any missing path by autodetection.
  handle('paths:get', async () => {
    const state = await pathsState();
    if (!state.gameDir || !state.configDir) await runAutodetect(false);
    return pathsState();
  });

  handle('paths:autodetect', async () => {
    const detected = await runAutodetect(true);
    return { detected, state: await pathsState() };
  });

  handle('paths:browse', async (kind) => {
    if (kind !== 'game' && kind !== 'config') throw new Error(`Unknown path kind: ${kind}`);
    const s = await settings.get();
    const current = kind === 'game' ? s.gameDir : s.configDir;
    const res = await dialog.showOpenDialog(mainWindow, {
      title: kind === 'game' ? 'Locate your RimWorld install folder' : "Locate RimWorld's Config folder (holds ModsConfig.xml)",
      defaultPath: current || (kind === 'config' ? paths.defaultConfigDir() : undefined) || undefined,
      properties: ['openDirectory'],
    });
    if (res.canceled || !res.filePaths.length) return { canceled: true, state: await pathsState() };
    const picked = res.filePaths[0];
    if (kind === 'game') {
      const gameDir = await paths.normalizeGameDir(picked);
      if (!gameDir) {
        throw new Error(`"${picked}" doesn't look like a RimWorld install folder (expected Data/Core or the RimWorld executable inside it).`);
      }
      await settings.update({ gameDir, gameSource: 'manual' });
    } else {
      const looksRight =
        path.basename(picked).toLowerCase() === 'config' || (await exists(modsConfig.modsConfigPath(picked)));
      if (!looksRight) {
        throw new Error(`"${picked}" doesn't look like RimWorld's Config folder (expected a folder named Config, or one containing ModsConfig.xml).`);
      }
      await settings.update({ configDir: picked });
    }
    return { canceled: false, state: await pathsState() };
  });

  // Scans <game>/Data (Core/DLC), <game>/Mods (SteamCMD downloads included),
  // and for Steam the Workshop folder (SCOPE.md §2; roots and priority in
  // paths.modRoots).
  handle('mods:scan', async () => {
    const state = await pathsState();
    if (!state.gameDir) throw new Error('RimWorld install folder is not set.');
    return scanModRoots(await paths.modRoots(state.gameDir));
  });

  // Selected mod's About/Preview.png as a data URL (null if none); the
  // sandboxed renderer can't load file:// paths itself.
  handle('mods:preview', (modDir) => (typeof modDir === 'string' && modDir ? readPreviewDataUrl(modDir) : null));

  // Mod-list context menu (SCOPE.md §4a).
  handle('settings:setModColor', (id, color) => settings.setModColor(id, color));
  handle('clipboard:writeText', (text) => {
    if (typeof text !== 'string') throw new Error('Clipboard expects text.');
    clipboard.writeText(text);
  });
  handle('clipboard:readText', () => clipboard.readText());

  // Mod list import/export (PLAN.md Phase 3; lib/modListIO.js). Importers return
  // { ids } (or { canceled: true }); the renderer applies them to the screen.
  handle('modList:importText', (text) => ({ ids: modListIO.detectAndParse(text) }));
  handle('modList:importRentry', async (url) => ({
    ids: modListIO.parseRentryPageHtml(await modListIO.fetchRentryPage(url, app.getVersion())),
  }));
  handle('modList:publishRentry', async (text) => {
    if (typeof text !== 'string' || !text) throw new Error('Nothing to publish.');
    return { url: await modListIO.publishRentry(text, app.getVersion()) };
  });
  handle('modList:importFile', async (kind) => {
    if (kind !== 'rimpy-xml' && kind !== 'save') throw new Error(`Unknown import kind: ${kind}`);
    const save = kind === 'save';
    const state = await pathsState();
    const res = await dialog.showOpenDialog(mainWindow, {
      title: save ? 'Read the mod list from a RimWorld save' : 'Import a RimPy mod list (.xml)',
      // Saves sits next to Config in RimWorld's user data folder.
      defaultPath: save && state.configDir ? path.join(path.dirname(state.configDir), 'Saves') : undefined,
      filters: save ? [{ name: 'RimWorld saves', extensions: ['rws'] }] : [{ name: 'RimPy mod list', extensions: ['xml'] }],
      properties: ['openFile'],
    });
    if (res.canceled || !res.filePaths.length) return { canceled: true };
    const file = res.filePaths[0];
    const ids = save ? await modListIO.readSaveModList(file) : modListIO.parseRimPyXmlText(await fs.readFile(file, 'utf8'));
    return { canceled: false, ids, path: file };
  });
  handle('modList:exportFile', async (activeIds) => {
    if (!Array.isArray(activeIds)) throw new Error('Export expects a list of mod ids.');
    // Same rule as Push: ids without a real packageId (folder: fallbacks,
    // workshop: pending placeholders) aren't written.
    const ids = cleanIds(activeIds).filter(isWritableId);
    const state = await pathsState();
    const res = await dialog.showSaveDialog(mainWindow, {
      title: 'Export the active list as a RimPy mod list',
      defaultPath: 'VOLT-export.xml',
      filters: [{ name: 'RimPy mod list', extensions: ['xml'] }],
    });
    if (res.canceled || !res.filePath) return { canceled: true };
    const eol = process.platform === 'win32' ? '\r\n' : '\n';
    await writeFileAtomic(res.filePath, modsConfig.freshModsConfig(ids, state.gameVersion, eol));
    return { canceled: false, path: res.filePath, count: ids.length };
  });
  handle('settings:setScanIssueIgnored', (p, ignored) => settings.setScanIssueIgnored(p, ignored));
  handle('settings:setSteamAcquireVia', (via) => settings.setSteamAcquireVia(via));
  handle('shell:openPath', async (p) => {
    if (typeof p !== 'string' || !(await exists(p))) throw new Error(`Folder not found: ${p}`);
    const err = await shell.openPath(p); // '' on success, an error string on failure
    if (err) throw new Error(err);
  });
  handle('shell:openExternal', async (url) => {
    // Only the Workshop page links the menu builds: https:// and steam://.
    if (typeof url !== 'string' || !/^(https:\/\/|steam:\/\/)/i.test(url)) throw new Error(`Refusing to open ${url}`);
    await shell.openExternal(url);
  });
  // Run: start the game via its executable in gameDir (first GAME_EXES match).
  handle('game:launch', async () => {
    const { gameDir } = await pathsState();
    let exe = null;
    if (gameDir) {
      for (const name of paths.GAME_EXES) {
        if (await exists(path.join(gameDir, name))) {
          exe = path.join(gameDir, name);
          break;
        }
      }
    }
    if (!exe) throw new Error(`No RimWorld executable found in ${gameDir || '(game folder not set)'}`);
    const err = await shell.openPath(exe); // '' on success, an error string on failure
    if (err) throw new Error(err);
  });

  // Steam Workshop subscribe/unsubscribe (PLAN.md item 4; lib/steam.js). Each
  // call re-checks the steam_appid.txt gate against the current game folder.
  // The Steam client never runs in this process: steam.js starts a short-lived
  // helper (lib/steamWorker.js, a utilityProcess) per Subscribe/Unsubscribe
  // operation and stops it when the operation ends. steam:available and
  // steam:deleteItemFolder start no helper.
  const steamGameDir = async () => (await pathsState()).gameDir;
  handle('steam:available', async () => steam.availability(await steamGameDir()));
  handle('steam:subscribe', async (id) => steam.subscribe(await steamGameDir(), id));
  handle('steam:unsubscribe', async (id) => steam.unsubscribe(await steamGameDir(), id));
  handle('steam:installInfo', async (id) => steam.installInfo(await steamGameDir(), id));
  handle('steam:isSubscribed', async (id) => steam.isSubscribed(await steamGameDir(), id));
  // Workshop listing via the logged-in client (one-shot helper): the Scan
  // Issues title lookup's fallback when steam:workshopTitles says not found.
  handle('steam:workshopItem', async (id) => steam.workshopItem(await steamGameDir(), id));
  // Ends the helper operation on an item (Sync to Steam's subscribe pass; see
  // steam.js release). Starts nothing, so no steam_appid.txt gate.
  handle('steam:release', async (id) => steam.release(id));
  // Unsubscribe's cleanup: best-effort delete of <Workshop content>/<id> (a
  // locked file is skipped, not fatal). The renderer passes an id, never a
  // path, so this can't be pointed anywhere else.
  handle('steam:deleteItemFolder', async (id) => {
    const gameDir = await steamGameDir();
    if (!gameDir || !(await paths.hasSteamAppId(gameDir))) {
      throw new Error("This isn't a Steam install, so there's no Workshop folder to clean up.");
    }
    const dir = path.join(paths.workshopDirFor(gameDir), steam.toItemId(id).toString());
    return { path: dir, ...(await removeTreeBestEffort(dir)) };
  });

  // Collection import (PLAN.md item 4; lib/steamWebApi.js): a pasted collection
  // URL/id -> { collectionId, title, items: [{ position, id, title, details }] }
  // via Steam's keyless Web API. Needs no Steam client, so it isn't gated on
  // steam_appid.txt; matching items to installed mods is the renderer's job.
  handle('steam:resolveCollection', (input) => steamWebApi.resolveCollection(input, app.getVersion()));

  // Workshop ids -> { id: listing title | null } (keyless Web API). Used by the
  // Scan Issues window to tell apart two duplicate-id mods whose About.xml names
  // are identical.
  // Per id: { title, found, result } - result is Steam's real EResult (1 = OK;
  // null when Steam's reply had no entry for the id), so a failed lookup is
  // distinguishable, and the IPC wrapper's "ok:" log line records it.
  handle('steam:workshopTitles', async (ids) =>
    Object.fromEntries(
      (await steamWebApi.getPublishedFileDetails(ids, app.getVersion())).map((d) => [
        d.id,
        { title: d.found ? d.title : null, found: d.found, result: d.result },
      ]),
    ),
  );

  // SteamCMD download (lib/steamCmd.js): Workshop ids -> ONE anonymous SteamCMD
  // session (live progress read from SteamCMD's own console log, since its
  // piped stdout is buffered until exit on Windows) into
  // APP-ROOT/steamcmd-library (never the real Steam library), then each item
  // copied into <game>/Mods/<id> so the game can load it. The
  // per-item result is best effort; the renderer rescans to see what landed.
  // Live progress is pushed to the window as 'steamcmd:progress' events
  // (preload.js onSteamCmdProgress; the status-bar row in App.jsx).
  const sendProgress = (ev) => {
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('steamcmd:progress', ev);
  };
  // mode: what each copy's marker records ('steamcmd' temporary / 'gog'
  // permanent; steamCmd.js MARKER_MODES), from the renderer's acquisition setting.
  handle('steamcmd:download', async (ids, mode) => steamCmd.downloadItems(appRoot, ids, (await pathsState()).modsDir, sendProgress, mode));
  // Pause: kill the running SteamCMD download (and cancel queued ones); the
  // pending steamcmd:download call then resolves with cancelled: true.
  handle('steamcmd:cancel', () => steamCmd.cancelCurrent());
  // Best-effort delete of a SteamCMD mod's Mods folder (its mod.path; main
  // checks it's a marked direct child of <game>/Mods): Unsubscribe on a
  // SteamCMD-only mod, and Sync to Steam's cleanup. Resolves with `gone`, which
  // callers must check - a locked file makes it false without throwing.
  handle('steamcmd:deleteItem', async (modPath) => steamCmd.deleteItem((await pathsState()).modsDir, modPath));

  handle('modsConfig:read', async () => {
    const state = await pathsState();
    if (!state.configDir) return { path: null, exists: false, version: null, activeMods: [], knownExpansions: [] };
    return modsConfig.readModsConfig(state.configDir);
  });

  // Push: the ONLY operation that writes the game's ModsConfig.xml (SCOPE.md §2a).
  handle('modsConfig:push', async (activeIds) => {
    if (!Array.isArray(activeIds)) throw new Error('Push expects a list of mod ids.');
    const state = await pathsState();
    if (!state.configDir) throw new Error("RimWorld's Config folder is not set.");
    return modsConfig.pushModsConfig(state.configDir, activeIds, { gameVersion: state.gameVersion });
  });

  handle('loadOrders:list', () => loadOrders.listLoadOrders(appRoot));

  handle('loadOrders:create', async (name, lists) => {
    const m = await loadOrders.createLoadOrder(appRoot, name, lists);
    await settings.update({ lastLoadOrder: m.slug });
    return m;
  });

  handle('loadOrders:load', async (slug) => {
    const m = await loadOrders.loadLoadOrder(appRoot, slug);
    await settings.update({ lastLoadOrder: m.slug });
    return m;
  });

  handle('loadOrders:save', (slug, lists) => loadOrders.saveLoadOrder(appRoot, slug, lists));

  // RimSort Community Rules Database for Sort (lib/communityRules.js): fetched
  // once per run, cached copy / empty on failure. The Map goes over IPC as a
  // plain object; the renderer rebuilds it (App.jsx).
  handle('communityRules:get', async () => {
    const { rules, source } = await communityRules.getCommunityRules(appRoot);
    return { rules: Object.fromEntries(rules), source };
  });
}

async function createWindow() {
  const { width, height } = await windowState.load();
  mainWindow = new BrowserWindow({
    width,
    height,
    minWidth: 1000,
    minHeight: 600,
    show: false,
    backgroundColor: '#1b1c1f',
    title: `V. O. L. T. v${app.getVersion()}`,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  // Keep the versioned window title rather than index.html's <title>.
  mainWindow.on('page-title-updated', (e) => e.preventDefault());
  mainWindow.once('ready-to-show', () => mainWindow.show());

  // Persist the user's chosen size (debounced - 'resize' fires continuously
  // while dragging), so the next launch reopens at the same size.
  let saveBoundsTimer = null;
  mainWindow.on('resize', () => {
    clearTimeout(saveBoundsTimer);
    saveBoundsTimer = setTimeout(() => {
      if (!mainWindow) return;
      const bounds = mainWindow.getBounds();
      windowState.save({ width: bounds.width, height: bounds.height })
        .catch((err) => log(`[windowState] save failed: ${err.message}`));
    }, 500);
  });

  mainWindow.on('closed', () => {
    clearTimeout(saveBoundsTimer);
    mainWindow = null;
  });

  // Never open new Electron windows; send http(s) links to the system browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });

  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) {
    mainWindow.loadURL(devUrl);
  } else {
    mainWindow.webContents.on('will-navigate', (e) => e.preventDefault());
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'renderer', 'index.html'));
  }
}

app.whenReady().then(async () => {
  console.log(`[volt] v${app.getVersion()} ready`);
  registerIpc();
  await createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

// Stop any Steam helper still running (lib/steam.js); Electron would take
// utility processes down with it anyway, this just asks them to exit first.
app.on('will-quit', () => {
  steam.stopAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
