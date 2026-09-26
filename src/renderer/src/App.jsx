import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, errMsg, rlog } from './api.js';
import { ACQUIRE_MODES, applyDownloadEvent, autoSortActive, blankLists, buildDependencyIndex, buildRentryMarkdown, buildRimSortText, effectiveAcquireVia, exportableIds, missingWorkshopRows, notFoundWorkshopId, officialIds, officialPhrase, reconcileLists, resolveWorkshopPlaceholders, runPool, sameIds, sortIdsByName, steamSubscribeAndWait, subscribeReady, syncSteamCmdMods, unsubscribeKind, usesSteamCmd, validateActive, workshopId } from './lists.js';
import PathsBar from './components/PathsBar.jsx';
import LoadOrderBar from './components/LoadOrderBar.jsx';
import ActionsColumn from './components/ActionsColumn.jsx';
import ModList from './components/ModList.jsx';
import DetailsPanel from './components/DetailsPanel.jsx';
import NameDialog from './components/NameDialog.jsx';
import CollectionDialog from './components/CollectionDialog.jsx';
import ContextMenu from './components/ContextMenu.jsx';
import ValidationWindow from './components/ValidationWindow.jsx';
import ScanIssuesWindow from './components/ScanIssuesWindow.jsx';
import SettingsWindow from './components/SettingsWindow.jsx';
import DownloadBar from './components/DownloadBar.jsx';
import GameSelect from './components/GameSelect.jsx';

const EMPTY_MODS = new Map();

// Steam Workshop Subscribe (PLAN.md item 4): after subscribing, poll Steam's
// install state every 2s until the item is on disk; give up after 2 minutes
// (Steam may still finish in the background). A subscribed flag that stays off
// for 3 polls in a row fails early (item missing/private/removed).
const SUBSCRIBE_POLL_MS = 2000;
const SUBSCRIBE_TIMEOUT_MS = 120_000;
const SUBSCRIBE_NOT_SUBSCRIBED_POLLS = 3;
// Unsubscribe: re-check Steam's subscribed flag up to 5 times, 1s apart,
// before touching any files (a resolved unsubscribe isn't proof it took).
const UNSUBSCRIBE_VERIFY_TRIES = 5;
const UNSUBSCRIBE_VERIFY_MS = 1000;
// Sync to Steam: how many SteamCMD mods are waited on at once in its install
// pass (lists.js syncSteamCmdMods; one Steam helper process each). Also the
// Steam-client mode's import batch (subscribeViaSteamworks). Untested on real
// hardware at 5: if Steam objects to that many at once (failed subscribes,
// helpers erroring), dial this down - 1 is the old one-at-a-time behavior.
const SYNC_CONCURRENCY = 5;
// Sync to Steam's subscribe pass (subscribe + verify, then the helper is
// released): how many run at once. Somewhat above SYNC_CONCURRENCY because
// each item holds its helper for only about a second (the user's real log
// showed 5 concurrent subscribe calls landing within ~130 ms), so this pass
// finishes a big list quickly - the point of it is registering every
// subscription up front. Capped rather than all at once: each in-flight item
// is its own helper process registered with Steam as "RimWorld running", and
// a 370-mod list must not spawn hundreds. Only 5 at once is real-hardware
// observed; if Steam objects at 8, set this back to SYNC_CONCURRENCY.
const SYNC_SUBSCRIBE_CONCURRENCY = 8;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
// Steam-client subscribe of one item (Subscribe, and the Steam-client mode's
// import batch): lists.js steamSubscribeAndWait wired to the IPC api.
const steamClient = api && { subscribe: api.steamSubscribe, installInfo: api.steamInstallInfo, sleep, log: rlog };
const SUBSCRIBE_WAIT = { pollMs: SUBSCRIBE_POLL_MS, timeoutMs: SUBSCRIBE_TIMEOUT_MS, notSubscribedPolls: SUBSCRIBE_NOT_SUBSCRIBED_POLLS };
const workshopPage = (wid) => `steam://url/CommunityFilePage/${wid}`;

export default function App() {
  return api ? <GameGate /> : <NoElectron />;
}

// Game-selection screen shell (PLAN.md §7): shown fresh on every launch,
// never remembered. Only RimWorld is wired up; picking it mounts the
// existing app unchanged. No refactor of Main below this gate.
function GameGate() {
  const [game, setGame] = useState(null);
  if (game !== 'rimworld') return <GameSelect onSelect={setGame} />;
  return <Main />;
}

function NoElectron() {
  return (
    <div className="center-message">
      <h2>V. O. L. T. must run inside Electron</h2>
      <p>Start it with dev.bat (or `npm run dev` in src/), not by opening the dev server URL in a browser.</p>
    </div>
  );
}

function Main() {
  const [info, setInfo] = useState(null);
  const [paths, setPaths] = useState(null);
  const [mods, setMods] = useState(EMPTY_MODS);
  const [problems, setProblems] = useState([]);
  const [active, setActive] = useState([]);
  const [inactive, setInactive] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  // (id, toggle): toggle=true (plain row click) clears an already-selected row;
  // right-click calls without it and always selects.
  const onSelectId = (id, toggle) => setSelectedId((prev) => (toggle && prev === id ? null : id));
  const [modColors, setModColors] = useState({}); // global, from settings.json
  // RimSort community sort rules: Map id -> { loadAfter, loadBefore }; empty
  // until the (non-blocking) boot fetch resolves, or if it finds nothing.
  const [communityRules, setCommunityRules] = useState(() => new Map());
  // Ignored scan problem paths (settings.json). A ref, not state: scanFor reads it
  // right after boot sets it, before a re-render would refresh the closure.
  const ignoredScanIssues = useRef([]);
  const [loadOrders, setLoadOrders] = useState([]);
  const [currentSlug, setCurrentSlug] = useState(null);
  // Baseline = the last saved/loaded active list; dirty is derived by comparing
  // against it, so an edit that reverts a previous one clears it. history is the
  // undo stack (pre-change active snapshots, most recent last) since that baseline.
  const [baselineActive, setBaselineActive] = useState([]);
  const [history, setHistory] = useState([]);
  const dirty = !sameIds(active, baselineActive);
  // Popup state. Create popup: { title, message, from: 'screen'|'blank', confirmLabel?, thenPush? }.
  // Save-before-Push popup: { savePush: true, title, message, confirmLabel, askName: false }.
  // rentry.co URL popup: { urlPrompt: true, title, message, confirmLabel, placeholder }.
  // Run-with-unsaved-changes popup: { runConfirm: true, askName: false, title, message, confirmLabel, confirmClass }.
  // Unsubscribe confirm popup: { unsubscribe: { wid, name }, askName: false, title, message, confirmLabel, confirmClass }.
  // Remove-SteamCMD-download popup (Unsubscribe on a SteamCMD-only mod): same shape, { removeDownload: { path, name }, ... } (path = the mod's Mods folder).
  const [dialog, setDialog] = useState(null);
  const [menu, setMenu] = useState(null); // Import/Export popup: { kind: 'import'|'export', x, y }
  const [dialogError, setDialogError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(null); // null, or { severity } (a count button) / { key } (a row icon)
  const [scanIssuesOpen, setScanIssuesOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Steam Workshop actions possible for this install (steam_appid.txt + the
  // steamworks.js package installed); refreshed whenever the paths are (re)loaded.
  const [steamAvailable, setSteamAvailable] = useState(false);
  const [downloading, setDownloading] = useState(() => new Set()); // not-found ids mid-Subscribe
  // SteamCMD download row in the status bar (DownloadBar.jsx); null = hidden.
  // rows/wids: everything requested since the row appeared (Resume re-runs
  // rows unchanged); done/failed/cur: live events (lists.js
  // applyDownloadEvent); active: downloadViaSteamCmd calls in flight;
  // cancelled: one of them came back cancelled; paused: all settled and at
  // least one was cancelled (the row stays); pausing: Pause clicked, waiting.
  const [dl, setDl] = useState(null);
  // Workshop id -> title for pending (not yet installed) collection items, so
  // their rows show a name instead of a bare id. In-memory only, never saved:
  // after a restart a pending row falls back to its id (PLAN.md item 4).
  const [workshopTitles, setWorkshopTitles] = useState(() => new Map());
  const [collectionOpen, setCollectionOpen] = useState(false); // "From Steam Workshop..." popup
  // Mod-acquisition mode (SCOPE.md §2a; settings.json steamAcquireVia,
  // Settings > Steam). acquireSetting: the stored choice, null = never chosen.
  // acquireVia: the mode in effect (lists.js effectiveAcquireVia) - 'steamcmd'
  // (default: SteamCMD into Mods, then Sync to Steam), 'steamworks' (the Steam
  // client directly) or 'gog' (SteamCMD into Mods, permanent, never synced;
  // auto-picked for a GOG install until the user chooses).
  const [acquireSetting, setAcquireSetting] = useState(null);
  const acquireVia = effectiveAcquireVia(acquireSetting, paths && paths.gameSource);
  const [syncing, setSyncing] = useState(false); // a Sync to Steam is running
  const [checkingMissing, setCheckingMissing] = useState(false); // "Check for missing Workshop mods" running
  const syncingRef = useRef(false); // same, readable before a re-render (two Sync clicks in a row)
  // Latest active list, for work that finishes long after it started (a
  // SteamCMD download's rescan) and must not restore a stale closure's list.
  const activeRef = useRef(active);
  activeRef.current = active;
  const [status, setStatus] = useState({ text: 'Starting...', kind: 'info' });
  const booted = useRef(false);
  const firstPrompted = useRef(false);

  const say = (text, kind = 'info') => setStatus({ text, kind });

  const run = async (fn) => {
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      say(errMsg(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const showLists = (map, activeIds) => {
    const lists = reconcileLists(map, activeIds);
    setActive(lists.active);
    setInactive(lists.inactive);
    return lists;
  };

  const resetBaseline = (newActive) => {
    setBaselineActive(newActive);
    setHistory([]);
  };

  const refreshSteam = () =>
    api.steamAvailable().then(
      (r) => setSteamAvailable(!!(r && r.available)),
      (err) => {
        setSteamAvailable(false);
        console.warn('[steam]', errMsg(err));
      },
    );

  const scanFor = async (p) => {
    if (!p || !p.modsDir) return EMPTY_MODS;
    const r = await api.scanMods();
    setProblems(r.problems.filter((x) => !ignoredScanIssues.current.includes(x.path)));
    return new Map(r.mods.map((m) => [m.id, m]));
  };

  // No load order open: show the game's current ModsConfig.xml (read-only).
  const showGameConfig = async (map) => {
    const cfg = await api.readModsConfig();
    resetBaseline(showLists(map, cfg.activeMods).active);
    say(
      cfg.exists
        ? `Showing the game's current ModsConfig.xml (${cfg.activeMods.length} active). Not saved to a load order yet.`
        : 'No ModsConfig.xml found. Activate mods, then Save to create a load order.',
    );
  };

  const openDialog = (d) => {
    setDialogError(null);
    setDialog(d);
  };

  // from: 'screen' copies the on-screen lists, 'blank' starts with only Core + DLC active.
  const openCreateDialog = (title, message, from, extra = {}) => openDialog({ title, message, from, ...extra });

  const promptFirstLoadOrder = () => {
    if (firstPrompted.current) return;
    firstPrompted.current = true;
    openCreateDialog(
      'Name your first load order',
      'Each load order gets its own folder in VOLT.',
      'screen',
      { toggleLabel: 'Import your current mod list (ModsConfig.xml)' },
    );
  };

  // Re-scan for (possibly new) paths, keeping the on-screen active list unless
  // the view is still just mirroring the game's ModsConfig.xml.
  const reloadForPaths = async (p) => {
    setPaths(p);
    refreshSteam();
    const map = await scanFor(p);
    if (!p.modsDir) setProblems([]);
    setMods(map);
    if (!currentSlug && !dirty) await showGameConfig(map);
    else showLists(map, active);
    if (!loadOrders.length && p.gameDir) promptFirstLoadOrder();
    return map;
  };

  useEffect(() => {
    if (booted.current) return; // StrictMode runs effects twice in dev
    booted.current = true;
    // Fetched in parallel with boot; never delays the scan. The IPC value is a
    // plain object (main.js), rebuilt as a Map here.
    api.getCommunityRules().then(
      (r) => setCommunityRules(new Map(Object.entries((r && r.rules) || {}))),
      (err) => console.warn('[communityRules]', errMsg(err)),
    );
    run(async () => {
      const [inf, st] = await Promise.all([api.getAppInfo(), api.getSettings()]);
      setInfo(inf);
      setModColors(st.modColors || {});
      setAcquireSetting(st.steamAcquireVia ?? null);
      ignoredScanIssues.current = st.ignoredScanIssues || [];
      const p = await api.getPaths();
      setPaths(p);
      refreshSteam();
      const map = await scanFor(p);
      setMods(map);
      const los = await api.listLoadOrders();
      setLoadOrders(los);
      const last = los.find((l) => l.slug === st.lastLoadOrder && !l.error);
      if (last) {
        const m = await api.loadLoadOrder(last.slug);
        setCurrentSlug(m.slug);
        resetBaseline(showLists(map, m.active).active);
        say(`Loaded load order "${m.name}".`);
        return;
      }
      await showGameConfig(map);
      if (!los.length && p.gameDir) promptFirstLoadOrder();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---- paths ----
  const onAutodetect = () =>
    run(async () => {
      const r = await api.autodetectPaths();
      await reloadForPaths(r.state);
      const g = r.detected.game;
      if (g) say(`Found RimWorld (${g.source === 'gog' ? 'GOG' : 'Steam'}) at ${g.gameDir}.`);
      else say("Autodetect didn't find a RimWorld install. Please locate it manually.", 'warn');
    });

  const onBrowse = (kind) =>
    run(async () => {
      const r = await api.browsePath(kind);
      if (r.canceled) return;
      await reloadForPaths(r.state);
      say(kind === 'game' ? `Game folder set to ${r.state.gameDir}.` : `Config folder set to ${r.state.configDir}.`);
    });

  const onOpenPath = (p) => api.openPath(p).catch((err) => say(errMsg(err), 'error'));

  const onRescan = () =>
    run(async () => {
      const map = await reloadForPaths(await api.getPaths());
      say(`Rescanned: ${map.size} mods found.`);
    });

  // ---- list editing ----
  // Each real change pushes the pre-change active list onto the undo stack.
  const pushHistory = () => setHistory((h) => [...h, active]);

  const activate = (id) => {
    if (active.includes(id)) return;
    pushHistory();
    setInactive((l) => l.filter((x) => x !== id));
    setActive([...active, id]);
  };

  const deactivate = (id) => {
    if (!active.includes(id)) return;
    pushHistory();
    setActive(active.filter((x) => x !== id));
    if (mods.has(id)) setInactive((l) => sortIdsByName([...l.filter((x) => x !== id), id], mods));
  };

  const reorder = (ids) => {
    if (sameIds(ids, active)) return; // no-op (e.g. Sort produced the same order)
    pushHistory();
    setActive(ids);
  };

  // Undo: restore the most recent history entry. Not itself a new change; no redo.
  const onUndo = () => {
    if (!history.length) return;
    setHistory((h) => h.slice(0, -1));
    showLists(mods, history[history.length - 1]); // recomputes inactive too
  };

  // Sort: reorder the active list by community sort rules plus each mod's own
  // loadAfter/loadBefore and modDependencies (lists.js autoSortActive). Only
  // changes the on-screen list; Save to keep it.
  const onSort = () => {
    const r = autoSortActive(active, mods, communityRules);
    reorder(r.active);
    say(
      `Sorted ${r.active.length} active mods.` +
        (r.unresolved
          ? ` ${r.unresolved} load order rule${r.unresolved === 1 ? '' : 's'} could not be satisfied (circular) and ${r.unresolved === 1 ? 'was' : 'were'} skipped.`
          : '') +
        (r.overridden
          ? ` ${r.overridden} About.xml rule${r.overridden === 1 ? '' : 's'} overridden by community sorting rules.`
          : '') +
        (r.dependencyConflicts
          ? ` ${r.dependencyConflicts} dependency ordering${r.dependencyConflicts === 1 ? '' : 's'} not applied: a community or About.xml load order rule says the opposite.`
          : ''),
      r.unresolved ? 'warn' : 'info',
    );
  };

  const onSetColor = useCallback((id, color) => {
    api.setModColor(id, color).then(setModColors, (err) => setStatus({ text: errMsg(err), kind: 'error' }));
  }, []);

  // ---- Steam Workshop subscribe / unsubscribe (PLAN.md item 4) ----
  const setDownloadingId = (id, on) =>
    setDownloading((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  // Subscribe to a "not found" entry whose id is a Workshop id, then wait for
  // Steam to download it. The row shows "downloading..." meanwhile; nothing is
  // rescanned automatically - the status line asks for a Rescan instead.
  const onSubscribe = async (id) => {
    const wid = notFoundWorkshopId(id, mods);
    if (!wid || downloading.has(id)) return;
    if (usesSteamCmd(acquireVia)) {
      downloadViaSteamCmd([id]);
      return;
    }
    setDownloadingId(id, true);
    say(`Subscribing to Workshop item ${wid}...`);
    rlog(`subscribe ${wid} (row ${id}): starting via Steam client`);
    try {
      await steamSubscribeAndWait(wid, steamClient, SUBSCRIBE_WAIT);
      say(`Subscribed to Workshop item ${wid} and Steam finished downloading it. Rescan to pick it up.`);
      return true;
    } catch (err) {
      rlog(`subscribe ${wid}: FAILED - ${errMsg(err)}`);
      say(
        `Couldn't subscribe to Workshop item ${wid}: ${errMsg(err)}. You can open its Workshop page in Steam instead: ${workshopPage(wid)}`,
        'error',
      );
      return false;
    } finally {
      setDownloadingId(id, false);
    }
  };

  // Rescan, keeping the latest on-screen active list (a pending row whose mod
  // is now on disk is swapped for it, lists.js reconcileLists).
  const rescanKeepingActive = async () => {
    const map = await scanFor(await api.getPaths());
    setMods(map);
    showLists(map, activeRef.current);
    return map;
  };

  // SteamCMD (Settings > Steam modes 'steamcmd' - the default - and 'gog'):
  // ONE download call (one
  // anonymous SteamCMD run) for every given
  // not-found Workshop row - a single Subscribe, or all of a
  // collection import's pending rows - into VOLT's own folder (main.js
  // steamcmd:download). Not run(): a big collection can take minutes and the
  // UI stays usable meanwhile. SteamCMD's own per-item report is only a hint;
  // the rescan afterwards decides: a row is done once its mod is on disk.
  // Anything still missing stays pending, its Subscribe button the retry.
  // Pause (status-bar row) kills the run (main.js steamcmd:cancel); the call
  // then resolves cancelled and the row flips to paused. Resume calls this
  // again with the same rows. The copies' marker records the mode in effect
  // ('gog' = permanent, else 'steamcmd' = temporary until Sync to Steam).
  const downloadViaSteamCmd = async (rowIds, startText) => {
    const rows = rowIds.filter((id) => notFoundWorkshopId(id, mods) && !downloading.has(id));
    if (!rows.length) return;
    const wids = [...new Set(rows.map((id) => notFoundWorkshopId(id, mods)))];
    setDownloading((prev) => new Set([...prev, ...rows]));
    setDl((d) => {
      const b = d || { rows: [], wids: [], done: [], failed: {}, cur: null, active: 0, cancelled: false, paused: false, pausing: false };
      return { ...b, rows: [...new Set([...b.rows, ...rows])], wids: [...new Set([...b.wids, ...wids])], active: b.active + 1, paused: false };
    });
    say(startText || `Downloading ${wids.length === 1 ? `Workshop item ${wids[0]}` : `${wids.length} Workshop items`} with SteamCMD...`);
    const mode = acquireVia === 'gog' ? 'gog' : 'steamcmd';
    rlog(`steamcmd download: ${wids.length} item(s) requested (mode ${mode}): ${wids.join(', ')}`);
    let report = null;
    let failure = null;
    let paused = false; // cancelled by Pause with something still missing
    try {
      report = await api.steamCmdDownload(wids, mode);
    } catch (err) {
      failure = errMsg(err);
      rlog(`steamcmd download: run FAILED - ${failure}`);
    }
    try {
      const map = await rescanKeepingActive();
      const onDisk = new Set([...map.values()].map(workshopId).filter(Boolean));
      const missing = wids.filter((w) => !onDisk.has(w));
      // Per-item outcome after the rescan (the real answer; SteamCMD's report is a hint).
      for (const w of wids) {
        const r = report?.results.find((x) => x.id === w);
        rlog(
          `steamcmd download ${w}: ${onDisk.has(w) ? 'on disk after rescan' : 'STILL MISSING, stays pending'}` +
            ` (SteamCMD reported ${r ? (r.ok === null ? 'nothing' : r.ok ? 'ok' : 'failed') : 'no result'}${r?.message ? `: ${r.message}` : ''})`,
        );
      }
      rlog(`steamcmd download: ${wids.length - missing.length} of ${wids.length} on disk${report?.cancelled ? ' (paused by the user)' : ''}`);
      if (report?.cancelled && missing.length) {
        paused = true;
        say(`SteamCMD download paused: ${wids.length - missing.length} of ${wids.length} Workshop item${wids.length === 1 ? '' : 's'} on disk. Resume continues it.`);
        return;
      }
      if (!missing.length) {
        say(wids.length === 1 ? `Downloaded Workshop item ${wids[0]} with SteamCMD.` : `Downloaded all ${wids.length} Workshop items with SteamCMD.`);
        return;
      }
      const why = failure || report?.results.find((r) => missing.includes(r.id) && r.message)?.message || report?.error;
      const done = wids.length - missing.length;
      say(
        (wids.length === 1
          ? `Couldn't download Workshop item ${wids[0]} with SteamCMD`
          : `Downloaded ${done} of ${wids.length} Workshop items with SteamCMD; ${missing.length} couldn't be downloaded and stay pending (Subscribe on a row retries it)`) +
          (why ? ` (${why})` : '') +
          '.' +
          (wids.length === 1 ? ` You can open its Workshop page in Steam instead: ${workshopPage(wids[0])}` : ''),
        done ? 'warn' : 'error',
      );
    } catch (err) {
      say(errMsg(err), 'error');
    } finally {
      setDownloading((prev) => {
        const next = new Set(prev);
        for (const id of rows) next.delete(id);
        return next;
      });
      // Paused only once the call has really settled cancelled (never on the
      // click itself: the run may finish on its own meanwhile).
      setDl((d) => {
        if (!d) return d;
        const active = d.active - 1;
        const cancelled = d.cancelled || paused;
        if (active > 0) return { ...d, active, cancelled };
        return cancelled ? { ...d, active: 0, cancelled: false, paused: true, pausing: false, cur: null } : null;
      });
    }
  };

  // Steam-client mode ('steamworks', Settings > Steam): subscribe every given
  // not-found Workshop row straight through Steam - what an import's pending
  // rows get automatically (acquirePending), the counterpart of the SteamCMD
  // modes' one download call. Each item runs Subscribe's own flow (lists.js
  // steamSubscribeAndWait), up to SYNC_CONCURRENCY at once (lists.js runPool,
  // the same worker pool Sync to Steam uses; one Steam helper each), then one
  // rescan resolves the finished rows. Not run(): a big collection takes a
  // while and the UI stays usable. A failed row stays pending, its Subscribe
  // button the retry.
  const subscribeViaSteamworks = async (rowIds) => {
    const rows = rowIds.filter((id) => notFoundWorkshopId(id, mods) && !downloading.has(id));
    if (!rows.length) return;
    if (!steamAvailable) {
      rlog(`steam subscribe batch: ${rows.length} row(s) left pending - Steam isn't available`);
      say(
        `${rows.length} Workshop mod${rows.length === 1 ? " isn't" : "s aren't"} installed and stay${rows.length === 1 ? 's' : ''} pending: Steam isn't available (not a Steam install, or the Steamworks library isn't installed). Switch Settings > Steam to a SteamCMD option to download ${rows.length === 1 ? 'it' : 'them'} without Steam.`,
        'warn',
      );
      return;
    }
    const rowsByWid = new Map();
    for (const id of rows) {
      const wid = notFoundWorkshopId(id, mods);
      rowsByWid.set(wid, [...(rowsByWid.get(wid) || []), id]);
    }
    const wids = [...rowsByWid.keys()];
    const total = wids.length;
    setDownloading((prev) => new Set([...prev, ...rows]));
    rlog(`steam subscribe batch: ${total} item(s), up to ${SYNC_CONCURRENCY} at once: ${wids.join(', ')}`);
    say(`Subscribing to ${total === 1 ? `Workshop item ${wids[0]}` : `${total} Workshop items`} on Steam...`);
    const failed = [];
    let done = 0;
    try {
      await runPool(wids, SYNC_CONCURRENCY, async (wid) => {
        try {
          await steamSubscribeAndWait(wid, steamClient, SUBSCRIBE_WAIT);
        } catch (err) {
          rlog(`subscribe ${wid}: FAILED - ${errMsg(err)}`);
          failed.push({ wid, error: errMsg(err) });
        } finally {
          done++;
          setDownloading((prev) => {
            const next = new Set(prev);
            for (const id of rowsByWid.get(wid)) next.delete(id);
            return next;
          });
          if (total > 1) say(`Subscribing on Steam: ${done}/${total} (${total - done} remaining)...`);
        }
      });
      await rescanKeepingActive();
      const ok = total - failed.length;
      rlog(`steam subscribe batch: ${ok} of ${total} subscribed and installed, ${failed.length} failed`);
      if (!failed.length) {
        say(total === 1 ? `Subscribed to Workshop item ${wids[0]} and Steam finished downloading it.` : `Subscribed to all ${total} Workshop items on Steam and Steam finished downloading them.`);
      } else if (total === 1) {
        say(`Couldn't subscribe to Workshop item ${wids[0]}: ${failed[0].error}. You can open its Workshop page in Steam instead: ${workshopPage(wids[0])}`, 'error');
      } else {
        say(
          `Subscribed to ${ok} of ${total} Workshop items on Steam; ${failed.length} couldn't be (${failed[0].error}) and stay pending (Subscribe on a row retries it; the log has each one's reason).`,
          ok ? 'warn' : 'error',
        );
      }
    } catch (err) {
      say(errMsg(err), 'error');
    } finally {
      setDownloading((prev) => {
        const next = new Set(prev);
        for (const id of rows) next.delete(id);
        return next;
      });
    }
  };

  // An import's pending rows (not-found Workshop ids), fetched right away by
  // the mode in effect: one SteamCMD download ('steamcmd' / 'gog') or
  // concurrent Steam-client subscribes ('steamworks').
  const acquirePending = (rowIds) => (usesSteamCmd(acquireVia) ? downloadViaSteamCmd(rowIds) : subscribeViaSteamworks(rowIds));

  // Live SteamCMD events, subscribed only while a download is in flight.
  const dlLive = !!dl && dl.active > 0;
  useEffect(() => {
    if (!dlLive) return undefined;
    return api.onSteamCmdProgress((ev) => setDl((d) => applyDownloadEvent(d, ev)));
  }, [dlLive]);

  // The row's pause/resume button. Resume re-runs the same rows (SteamCMD's
  // cache skips what already finished).
  const onToggleDownloadPause = async () => {
    if (!dl || dl.pausing) return;
    if (dl.paused) {
      rlog(`steamcmd download: resume requested for ${dl.rows.length} row(s): ${dl.rows.join(', ')}`);
      if (!dl.rows.some((id) => notFoundWorkshopId(id, mods))) {
        setDl(null);
        return;
      }
      downloadViaSteamCmd(dl.rows, `Resuming the SteamCMD download (${dl.wids.length} Workshop item${dl.wids.length === 1 ? '' : 's'})...`);
      return;
    }
    rlog('steamcmd download: pause requested');
    setDl((d) => d && { ...d, pausing: true });
    try {
      const stopped = await api.steamCmdCancel();
      rlog(`steamcmd download: cancel ${stopped ? 'sent' : 'found nothing running'}`);
      if (!stopped) setDl((d) => d && { ...d, pausing: false });
    } catch (err) {
      setDl((d) => d && { ...d, pausing: false });
      say(errMsg(err), 'error');
    }
  };

  // "Check for missing Workshop mods" (Settings > Steam): re-fetch every
  // not-found Workshop row in the active list (e.g. a mod re-subscribed on
  // Steam whose redownload never finished). SteamCMD: the same one download call
  // collection import uses (it rescans and reports). Steam client: each row's
  // own Subscribe flow, one at a time, then one rescan.
  const checkMissingWorkshop = async () => {
    if (checkingMissing) return;
    const rows = missingWorkshopRows(active, mods).filter((id) => !downloading.has(id));
    if (!rows.length) {
      say('Nothing to check: every Workshop mod in the active list is installed.');
      return;
    }
    if (!subscribeReady(acquireVia, steamAvailable)) {
      say("Steam isn't available (not a Steam install, or the Steamworks library isn't installed), so nothing was checked. Switch Download mods via to SteamCMD to download them without Steam.", 'warn');
      return;
    }
    const checking = `Checking ${rows.length} missing mod${rows.length === 1 ? '' : 's'}...`;
    rlog(`check missing workshop mods: ${rows.length} row(s): ${rows.join(', ')} (via ${acquireVia})`);
    setCheckingMissing(true);
    try {
      if (usesSteamCmd(acquireVia)) {
        await downloadViaSteamCmd(rows, checking);
        return;
      }
      say(checking);
      let ok = 0;
      for (const id of rows) if (await onSubscribe(id)) ok++;
      await rescanKeepingActive();
      say(
        `Checked ${rows.length} missing mod${rows.length === 1 ? '' : 's'}: Steam downloaded ${ok}.` +
          (ok < rows.length ? ` ${rows.length - ok} couldn't be downloaded and stay not found (the log has why).` : ''),
        ok === rows.length ? 'info' : ok ? 'warn' : 'error',
      );
    } catch (err) {
      say(errMsg(err), 'error');
    } finally {
      setCheckingMissing(false);
    }
  };

  const onSetAcquireVia = useCallback((via) => {
    api.setSteamAcquireVia(via).then(setAcquireSetting, (err) => setStatus({ text: errMsg(err), kind: 'error' }));
  }, []);

  // Sync to Steam (PLAN.md item 4): make every SteamCMD-downloaded mod a real
  // Steam subscription, then drop its SteamCMD copy (lists.js syncSteamCmdMods;
  // Steamworks via the existing worker-isolated steam:* calls). Not run(): each
  // item takes a few seconds, so the UI stays usable and the status bar reports.
  // Run only from the actions column's Sync button (never by Save).
  const syncToSteam = async () => {
    if (syncingRef.current) {
      say('A Sync to Steam is already running.');
      return;
    }
    const count = [...mods.values()].filter((m) => m.source === 'steamcmd' && workshopId(m)).length;
    if (!steamAvailable) {
      say("Steam isn't available (not a Steam install, or the Steamworks library isn't installed), so nothing was synced.", 'warn');
      return;
    }
    if (!count) {
      say('Nothing to sync: every Workshop mod is already subscribed on Steam.');
      return;
    }
    syncingRef.current = true;
    setSyncing(true);
    say(`Syncing ${count} SteamCMD-downloaded mod${count === 1 ? '' : 's'} to Steam...`);
    try {
      const r = await syncSteamCmdMods(mods, {
        subscribe: api.steamSubscribe,
        isSubscribed: api.steamIsSubscribed,
        installInfo: api.steamInstallInfo,
        deleteCopy: api.steamCmdDeleteItem,
        release: api.steamRelease,
        sleep,
        log: rlog,
      }, {
        tries: UNSUBSCRIBE_VERIFY_TRIES,
        waitMs: UNSUBSCRIBE_VERIFY_MS,
        pollMs: SUBSCRIBE_POLL_MS,
        timeoutMs: SUBSCRIBE_TIMEOUT_MS,
        concurrency: SYNC_CONCURRENCY,
        subscribeConcurrency: SYNC_SUBSCRIBE_CONCURRENCY,
        onProgress: (done, total) => say(`Syncing to Steam: ${done}/${total} (${total - done} remaining)...`),
      });
      // pending can have changed disk too (a partly deleted copy)
      if (r.synced.length || r.pending.length) await rescanKeepingActive();
      const n = r.synced.length;
      say(
        `Synced ${n} of ${r.total} mod${r.total === 1 ? '' : 's'} to Steam.` +
          (n ? ' Steam downloaded them into its Workshop folder and their SteamCMD copies were removed.' : '') +
          (r.pending.length
            ? ` ${r.pending.length} ${r.pending.length === 1 ? 'is' : 'are'} subscribed on Steam but still ${r.pending.length === 1 ? 'has its SteamCMD copy' : 'have their SteamCMD copies'} (Steam didn't confirm the download within ${SUBSCRIBE_TIMEOUT_MS / 1000} seconds, or a file in the copy was locked or in use - the log says which); the next sync finishes ${r.pending.length === 1 ? 'it' : 'them'}.`
            : '') +
          (r.failed.length
            ? ` ${r.failed.length} couldn't be subscribed (${r.failed[0].error}) and stay as SteamCMD downloads until the next sync.`
            : ''),
        r.failed.length ? (n || r.pending.length ? 'warn' : 'error') : r.pending.length ? 'warn' : 'info',
      );
    } catch (err) {
      say(errMsg(err), 'error');
    } finally {
      syncingRef.current = false;
      setSyncing(false);
    }
  };

  // Unsubscribe from an installed Workshop mod: destructive, so it confirms first.
  // A SteamCMD download (source 'steamcmd') was never subscribed on Steam, so
  // it only has its files deleted (no Steamworks call); a real subscription
  // (source 'workshop') gets the unsubscribe-verify-delete flow below.
  const onUnsubscribe = (id) => {
    const mod = mods.get(id);
    const kind = unsubscribeKind(mod);
    if (!kind) return;
    const wid = workshopId(mod);
    if (kind === 'delete') {
      openDialog({
        removeDownload: { path: mod.path, name: mod.name },
        askName: false,
        title: `Remove ${mod.name}?`,
        message: [
          `This mod was downloaded with SteamCMD and isn't subscribed on Steam, so this only deletes its folder from RimWorld's Mods folder (${mod.path}).`,
          "Removing files is best-effort: a file that's locked or in use is skipped rather than failing the whole operation.",
        ].join('\n\n'),
        confirmLabel: 'Remove',
        confirmClass: 'danger',
      });
      return;
    }
    openDialog({
      unsubscribe: { wid, name: mod.name },
      askName: false,
      title: `Unsubscribe from ${mod.name}?`,
      message: [
        `This unsubscribes you from the mod on Steam, then also removes any files left in its own Workshop folder (${mod.path}).`,
        "Removing files is best-effort: a file that's locked or in use is skipped rather than failing the whole operation.",
      ].join('\n\n'),
      confirmLabel: 'Unsubscribe',
      confirmClass: 'danger',
    });
  };

  // Unsubscribe, verify Steam really dropped it (RimSort's silent-failure bug,
  // PLAN.md item 4), and only then delete the mod's Workshop folder.
  const unsubscribeNow = ({ wid, name }) =>
    run(async () => {
      say(`Unsubscribing from ${name}...`);
      rlog(`unsubscribe ${wid} (${name}): starting`);
      await api.steamUnsubscribe(wid);
      let still = true;
      for (let i = 0; i < UNSUBSCRIBE_VERIFY_TRIES && still; i++) {
        if (i) await sleep(UNSUBSCRIBE_VERIFY_MS);
        still = await api.steamIsSubscribed(wid);
        rlog(`unsubscribe ${wid}: isSubscribed check ${i + 1}/${UNSUBSCRIBE_VERIFY_TRIES} -> ${still}`);
      }
      if (still) {
        rlog(`unsubscribe ${wid}: FAILED - still subscribed, files left alone`);
        throw new Error(
          `Steam still lists you as subscribed to ${name} after unsubscribing, so its files were left alone. Try again, or unsubscribe from its Workshop page in Steam: ${workshopPage(wid)}`,
        );
      }
      const r = await api.steamDeleteItemFolder(wid);
      const left = r.skipped.length;
      rlog(`unsubscribe ${wid}: verified; Workshop folder ${r.path} ${r.gone ? 'removed' : `partly removed, ${left} item(s) left`}`);
      say(
        `Unsubscribed from ${name}` +
          (r.gone
            ? ' and removed its Workshop folder.'
            : left
              ? `. ${left} item${left === 1 ? ' was' : 's were'} locked or in use and left behind in ${r.path}.`
              : '.') +
          ' Rescan to update the lists.',
        left ? 'warn' : 'info',
      );
    });

  // Unsubscribe on a SteamCMD-only mod: delete its downloaded folder, nothing
  // else. The delete is best effort and doesn't throw for a locked file, so
  // `gone` is the only real answer: false = the folder is still there, not
  // removed (steamCmd.js deleteItem keeps it recognisable, so this can retry).
  const removeDownloadNow = ({ path, name }) =>
    run(async () => {
      const r = await api.steamCmdDeleteItem(path);
      const left = r.skipped.length;
      rlog(
        `remove download ${r.path} (${name}): ` +
          (r.gone ? 'removed' : `NOT removed - folder still on disk, ${left} item(s) couldn't be deleted: ${r.skipped.map((s) => `${s.path} (${s.error})`).join('; ')}`),
      );
      say(
        (r.gone
          ? `Removed ${name}'s SteamCMD download.`
          : `Couldn't fully remove ${name}'s SteamCMD download: ${left ? `${left} item${left === 1 ? ' was' : 's were'} locked or in use` : "its folder couldn't be deleted"}, so it's still in ${r.path}. Close whatever is using it (the game, say) and remove it again.`) +
          ' Rescan to update the lists.',
        r.gone ? 'info' : 'warn',
      );
    });

  // ---- load orders ----
  const onSelectLoadOrder = (slug) => {
    if (slug === currentSlug) return;
    if (dirty && !window.confirm('Discard unsaved changes to the current list?')) return;
    run(async () => {
      const m = await api.loadLoadOrder(slug);
      setCurrentSlug(m.slug);
      resetBaseline(showLists(mods, m.active).active);
      say(`Loaded load order "${m.name}".`);
    });
  };

  const onNew = () => {
    if (dirty && !window.confirm('Discard unsaved changes to the current list?')) return;
    openCreateDialog(
      'New load order',
      'Starts blank: only Core and the installed DLCs are active; every other mod starts inactive.',
      'blank',
    );
  };

  const onCopy = () =>
    openCreateDialog(
      'Copy to new load order',
      `Copy the load order on screen (${active.length} active mods${dirty ? ', including unsaved changes' : ''}) into a new load order?`,
      'screen',
      { confirmLabel: 'Copy' },
    );

  const onCreate = async (name, checked) => {
    // An unchecked import toggle (first-launch popup) means start blank.
    const from = dialog.toggleLabel && !checked ? 'blank' : dialog.from;
    const lists = from === 'blank' ? blankLists(mods) : { active, inactive };
    setBusy(true);
    setDialogError(null);
    let created = false;
    try {
      const m = await api.createLoadOrder(name, lists);
      created = true;
      setDialog(null);
      setCurrentSlug(m.slug);
      setActive(lists.active);
      setInactive(lists.inactive);
      resetBaseline(lists.active);
      setLoadOrders(await api.listLoadOrders());
      say(`Created load order "${m.name}" (folder load-orders/${m.slug}/).`);
      if (dialog.thenPush) await pushNow(lists.active);
    } catch (err) {
      if (created) say(errMsg(err), 'error'); // the Push after a successful create failed
      else setDialogError(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  // Save: current lists -> the load order's manifest. Never touches the game.
  const saveNow = async () => {
    const m = await api.saveLoadOrder(currentSlug, { active, inactive });
    resetBaseline(active);
    setLoadOrders(await api.listLoadOrders());
    say(`Saved load order "${m.name}" (${m.active.length} active).`);
  };

  const onSave = () => {
    if (!currentSlug) {
      openCreateDialog('Save as a new load order', "This list isn't part of a load order yet. Name it to save it.", 'screen');
      return;
    }
    run(saveNow);
  };

  // Push: the active list -> the game's real ModsConfig.xml. The only write to
  // it. Only a saved load order is pushed (SCOPE.md §2a).
  const pushDetails = () => {
    // Pending workshop:<id> placeholders aren't written (skipped main-side, ids.js
    // isWritableId), so they get their own line instead of the not-found count.
    const pending = active.filter((id) => id.startsWith('workshop:')).length;
    const notFound = active.filter((id) => !mods.has(id) && !id.startsWith('workshop:')).length;
    const lines = [`Target: ${paths.modsConfigPath}`];
    if (notFound) {
      lines.push(
        `${notFound} active mods weren't found in the game's Data or Mods folder (or the Steam Workshop folder); they are written as-is.`,
      );
    }
    if (pending) {
      lines.push(
        `${pending} pending Workshop mod${pending === 1 ? '' : 's'} (not downloaded yet) will be skipped; they stay in the load order but aren't written.`,
      );
    }
    lines.push('The current file is backed up to ModsConfig.xml.volt-backup first.');
    return lines;
  };

  const pushNow = async (ids) => {
    const r = await api.pushModsConfig(ids);
    say(`Pushed ${r.count} active mods to ${r.path}.` + (r.skipped ? ` Skipped ${r.skipped} without a packageId.` : ''));
  };

  const onPush = () => {
    if (!paths || !paths.configDir) return;
    if (dirty) {
      openDialog({
        savePush: true,
        askName: false,
        title: 'Save before pushing',
        message: [
          `This load order has unsaved changes. Push only writes a saved load order, so it has to be saved first; then its active list (${active.length} mods, in this order) is written to the game's ModsConfig.xml.`,
          ...pushDetails(),
        ].join('\n\n'),
        confirmLabel: 'Save & Push',
      });
      return;
    }
    const lines = [`Write the active list (${active.length} mods, in this order) to the game's ModsConfig.xml?`, ...pushDetails()];
    if (!window.confirm(lines.join('\n\n'))) return;
    run(() => pushNow(active));
  };

  // Run: launch the game (main.js game:launch). Never saves or pushes; with
  // unsaved changes it asks first (SCOPE.md §3).
  const launchNow = () =>
    api.launchGame().then(
      () => say('Launching RimWorld...'),
      (err) => say(errMsg(err), 'error'),
    );

  const onRun = () => {
    if (!dirty) {
      launchNow();
      return;
    }
    openDialog({
      runConfirm: true,
      askName: false,
      title: 'Unsaved load order changes',
      message:
        "The active list has unsaved changes. Run doesn't save or push them: RimWorld starts with the mod list last pushed to its ModsConfig.xml.",
      confirmLabel: 'Run without saving',
      confirmClass: 'warn-outline',
    });
  };

  const onSaveAndPush = () => {
    if (!currentSlug) {
      // Nothing to save into yet: name a new load order (copy of the screen), then push.
      openCreateDialog(
        'Save as a new load order',
        "This list isn't part of a load order yet. Name it to save it; it's pushed right after.",
        'screen',
        { confirmLabel: 'Create & Push', thenPush: true },
      );
      return;
    }
    setDialog(null);
    run(async () => {
      await saveNow();
      await pushNow(active);
    });
  };

  // ---- import / export (PLAN.md Phase 3) ----
  // An import replaces the whole active list like loading a load order, but
  // stays an undoable, unsaved edit (baseline untouched). keepPending (collection
  // import): an uninstalled Workshop item stays as a "workshop:<id>" pending
  // row instead of being skipped. official (collection import): official ids
  // put at the top of the list too, but not counted as coming from `source`.
  const applyImport = (rawIds, source, { keepPending = false, official = [] } = {}) => {
    const { ids, skipped, pending } = resolveWorkshopPlaceholders([...official, ...rawIds], mods, { keepUnmatched: keepPending });
    if (ids.length === official.length) {
      say(`None of the ${skipped} Workshop mods on the page are installed, so nothing was imported. Subscribe to them on Steam, rescan, then re-import.`, 'warn');
      return;
    }
    pushHistory();
    showLists(mods, ids);
    const notFound = ids.filter((id) => !mods.has(id)).length - pending;
    say(
      `Imported ${ids.length - official.length} mods from ${source}` +
        (official.length ? `; ${officialPhrase(official)} ${official.length === 1 ? 'is' : 'are'} active too.` : '.') +
        (notFound
          ? ` ${notFound} of them weren't found in the game's Data or Mods folder (or the Steam Workshop folder); they're kept as-is.`
          : '') +
        (pending
          ? ` ${pending} ${pending === 1 ? "isn't" : "aren't"} installed yet and ${pending === 1 ? 'is' : 'are'} shown as pending; Subscribe downloads ${pending === 1 ? 'it' : 'them'}.`
          : '') +
        (skipped
          ? ` ${skipped} Workshop mods on the page aren't installed and were skipped; subscribe to them on Steam, rescan, then re-import.`
          : ''),
      skipped ? 'warn' : 'info',
    );
    return ids;
  };

  const confirmReplace = () => !dirty || window.confirm('Discard unsaved changes to the current list?');

  const onImportClipboard = () => {
    if (!confirmReplace()) return;
    run(async () => {
      const r = await api.importModListText(await api.readClipboard());
      applyImport(r.ids, 'the clipboard');
    });
  };

  const onImportFile = (kind) => {
    if (!confirmReplace()) return;
    run(async () => {
      const r = await api.importModListFile(kind);
      if (r.canceled) return;
      applyImport(r.ids, kind === 'save' ? 'the save' : 'the RimPy file');
    });
  };

  const onImportRentry = () => {
    if (!confirmReplace()) return;
    openDialog({
      urlPrompt: true,
      title: 'Import from rentry.co',
      message: "Paste the rentry.co page's URL \u2014 the one you'd share, or its /edit link both work.",
      confirmLabel: 'Import',
      placeholder: 'https://rentry.co/example',
    });
  };

  // Keeps the popup open with the error on failure, like onCreate.
  const onRentryConfirm = async (url) => {
    setBusy(true);
    setDialogError(null);
    try {
      const r = await api.importModListFromRentry(url);
      setDialog(null);
      applyImport(r.ids, 'rentry.co');
    } catch (err) {
      setDialogError(errMsg(err));
    } finally {
      setBusy(false);
    }
  };

  // "From Steam Workshop...": the popup resolves the collection and matches
  // it against the scan itself (CollectionDialog.jsx); it hands back the ordered
  // ids (packageIds / "workshop:<id>" placeholders) plus each item's title.
  // No discard prompt here: only a collection's Replace list / New load order
  // swaps the list, so onCollectionImport asks then.
  const onImportCollection = () => setCollectionOpen(true);

  // A collection's r.mode: 'add' appends to the active list (nothing is lost, no
  // prompt); 'replace' and 'new' swap the whole list, so they ask to discard
  // unsaved changes first - declining keeps the popup open. 'new' then names a
  // new load order from the screen, so the next Save can't overwrite the one
  // that was open.
  const onCollectionImport = (r) => {
    if (!r.single && r.mode !== 'add' && !confirmReplace()) return;
    setCollectionOpen(false);
    const titles = r.items.filter((it) => it.title);
    if (titles.length) {
      setWorkshopTitles((prev) => {
        const next = new Map(prev);
        for (const it of titles) next.set(it.id, it.title);
        return next;
      });
    }
    // A single mod's link: appended to the current active list (activate), not
    // a list replacement; not found yet -> the same pending row + auto-download.
    if (r.single) {
      const id = r.ids[0];
      const name = r.title ? `"${r.title}"` : `Workshop item ${r.collectionId}`;
      const pending = !!notFoundWorkshopId(id, mods);
      if (active.includes(id)) say(`${name} is already in the active list.`);
      else {
        activate(id);
        say(`Added ${name} to the end of the active list${pending ? ' as pending; Subscribe downloads it' : ''}.`);
      }
      if (pending) acquirePending([id]);
      return;
    }
    const source = r.title ? `the Steam collection "${r.title}"` : `Steam collection ${r.collectionId}`;
    const before = [...active]; // New load order...: cancelling the name popup puts this back
    // Core + DLC: a Workshop collection can only hold Workshop items, so every
    // scanned official id (lists.js officialIds) is made active too, whatever
    // the mode. Kept apart from r.ids so no message counts them as coming from
    // the collection.
    const allOfficial = officialIds(mods);
    const official = allOfficial.filter((id) => !r.ids.includes(id));
    // Add to list: one undo step for the whole batch (activate() per id would
    // push one each); ids already active are left where they are.
    if (r.mode === 'add') {
      const uniq = [...new Set(r.ids)];
      const added = uniq.filter((id) => !active.includes(id));
      const already = uniq.length - added.length;
      const pending = added.filter((id) => notFoundWorkshopId(id, mods)).length;
      // Missing official ids go at the top, never after the mods: right after
      // the list's leading run of official ids, or first if the first official
      // id in load order (Core) is itself missing.
      const addedOfficial = official.filter((id) => !active.includes(id));
      if (added.length || addedOfficial.length) {
        const addedSet = new Set([...addedOfficial, ...added]);
        let at = active.findIndex((id) => !allOfficial.includes(id));
        if (at < 0) at = active.length;
        if (addedOfficial[0] === allOfficial[0]) at = 0;
        pushHistory();
        setInactive((l) => l.filter((x) => !addedSet.has(x)));
        setActive([...active.slice(0, at), ...addedOfficial, ...active.slice(at), ...added]);
      }
      say(
        (added.length
          ? `Added ${added.length} mod${added.length === 1 ? '' : 's'} from ${source} to the end of the active list.`
          : addedOfficial.length
            ? `No mods added from ${source}: all ${uniq.length} are already in the active list.`
            : `Nothing added: all ${uniq.length} mods from ${source} are already in the active list.`) +
          (added.length && already ? ` ${already} ${already === 1 ? 'was' : 'were'} already active and stayed where ${already === 1 ? 'it was' : 'they were'}.` : '') +
          (pending
            ? ` ${pending} ${pending === 1 ? "isn't" : "aren't"} installed yet and ${pending === 1 ? 'is' : 'are'} shown as pending; Subscribe downloads ${pending === 1 ? 'it' : 'them'}.`
            : '') +
          (addedOfficial.length
            ? ` ${officialPhrase(addedOfficial)} ${addedOfficial.length === 1 ? 'was' : 'were'} also made active, at the top of the list (a Steam collection can't include official content).`
            : ''),
      );
      if (pending) acquirePending(added);
      return;
    }
    const ids = applyImport(r.ids, source, { keepPending: true, official });
    // Every pending item is fetched right away, by the mode in effect: one
    // SteamCMD download call, or concurrent Steam-client subscribes.
    if (ids) acquirePending(ids);
    // New load order...: the collection is on screen now; 'screen' saves exactly that.
    if (ids && r.mode === 'new') {
      openCreateDialog(
        'New load order from Steam Workshop',
        `Save the ${ids.length - official.length} mods imported from ${source}${official.length ? ` (plus ${officialPhrase(official)})` : ''} as a new load order?` +
          (currentSlug ? ' The load order you had open stays as it was last saved.' : ''),
        'screen',
        { revertOnCancel: before },
      );
    }
  };

  // Shared exports leave pending workshop:<id> placeholders and no-packageId
  // folder:<name> ids out (lists.js exportableIds).
  const rimSortText = (ids) => buildRimSortText(ids, mods, info && info.version, paths && paths.gameVersion);

  const onPublishRentry = () =>
    run(async () => {
      const { url } = await api.publishRentryList(
        buildRentryMarkdown(exportableIds(active), mods, info && info.version, paths && paths.gameVersion),
      );
      await api.copyText(url);
      say(`Published to rentry.co: ${url} (copied to clipboard).`);
    });

  const onExportRentry = () =>
    run(async () => {
      const ids = exportableIds(active);
      await api.copyText(rimSortText(ids));
      say(`Copied ${ids.length} mods to the clipboard in RimSort/rentry.co format.`);
    });

  const onExportRimPy = () =>
    run(async () => {
      const r = await api.exportModListFile(active);
      if (r.canceled) return;
      say(`Exported ${r.count} mods to ${r.path}.`);
    });

  const openMenu = (kind) => (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    setMenu({ kind, x: r.left, y: r.bottom + 4 });
  };
  const closeMenu = useCallback(() => setMenu(null), []);
  const menuItems =
    menu && menu.kind === 'import'
      ? [
          { label: 'From clipboard', onClick: onImportClipboard },
          { label: 'From RimPy .xml file...', onClick: () => onImportFile('rimpy-xml') },
          { label: 'From rentry.co...', onClick: onImportRentry },
          { label: 'Read from save...', onClick: () => onImportFile('save') },
          { label: 'From Steam Workshop...', onClick: onImportCollection },
        ]
      : [
          { label: 'Rentry (share link)', onClick: onPublishRentry },
          { label: 'Clipboard (RimSort)', onClick: onExportRentry },
          { label: '.xml (RimPy)', onClick: onExportRimPy },
        ];

  const noGame = paths && !paths.gameDir;
  const gameVersion = paths ? paths.gameVersion : null;

  // modDependencies of the selected mod, and mods depending on it: highlighted in both panes.
  const depIndex = useMemo(() => buildDependencyIndex(mods), [mods]);
  const dependencyIds = selectedId ? depIndex.dependsOn.get(selectedId) : undefined;
  const dependentIds = selectedId ? depIndex.dependedOnBy.get(selectedId) : undefined;
  const selectedWid = selectedId ? notFoundWorkshopId(selectedId, mods) : null;

  // Load-order violations / missing dependencies / hard conflicts (Phase 2b,
  // warn-only): recomputed on every active-list change (add, remove, reorder,
  // sort, load) and when community rules arrive. Never gates Save/Push.
  const validation = useMemo(() => validateActive(active, mods, communityRules), [active, mods, communityRules]);
  const warningCount = validation.issues.filter((i) => i.severity === 'warning').length;
  const errorCount = validation.issues.length - warningCount;
  const issuesByMod = useMemo(() => {
    const map = new Map();
    for (const i of validation.issues) {
      if (!map.has(i.modId)) map.set(i.modId, []);
      map.get(i.modId).push(i);
    }
    return map;
  }, [validation]);
  const showIssue = useCallback((key) => setIssuesOpen({ key }), []);
  const closeIssues = useCallback(() => setIssuesOpen(null), []);
  const closeScanIssues = useCallback(() => setScanIssuesOpen(false), []);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const ignoreScanIssue = useCallback((p) => {
    api.setScanIssueIgnored(p, true).then((list) => {
      ignoredScanIssues.current = list;
      setProblems((prev) => prev.filter((x) => x.path !== p));
    }, (err) => setStatus({ text: errMsg(err), kind: 'error' }));
  }, []);

  return (
    <div className="app">
      <PathsBar paths={paths} appVersion={info && info.version} onOpenPath={onOpenPath} onSettings={() => setSettingsOpen(true)} />
      <LoadOrderBar
        loadOrders={loadOrders}
        currentSlug={currentSlug}
        dirty={dirty}
        disabled={busy || !!noGame}
        onSelect={onSelectLoadOrder}
        onNew={onNew}
        onCopy={onCopy}
        onUndo={onUndo}
        gameVersion={gameVersion}
      />
      <div className="content-row">
        {noGame ? (
          <div className="center-message">
            <h2>Couldn't find RimWorld</h2>
            <p>
              {paths.savedGameDirMissing
                ? 'The saved RimWorld folder no longer exists.'
                : "Autodetect didn't find a Steam or GOG install of RimWorld."}{' '}
              Please locate your RimWorld install folder (the one containing Data and Mods).
            </p>
            <div className="button-row">
              <button className="primary" onClick={() => onBrowse('game')} disabled={busy}>
                Locate RimWorld folder...
              </button>
              <button onClick={onAutodetect} disabled={busy}>
                Try autodetect again
              </button>
            </div>
          </div>
        ) : (
          <main className="main">
            <DetailsPanel
              id={selectedId}
              mod={selectedId ? mods.get(selectedId) : null}
              pendingTitle={selectedWid ? workshopTitles.get(selectedWid) : undefined}
            />
            <ModList
              title="Inactive"
              ids={inactive}
              mods={mods}
              selectedId={selectedId}
              onSelect={onSelectId}
              onActivate={activate}
              emptyText="No inactive mods"
              modColors={modColors}
              onSetColor={onSetColor}
              say={say}
              gameVersion={gameVersion}
              dependencyIds={dependencyIds}
              dependentIds={dependentIds}
              conflicts={validation.conflicts}
              steamAvailable={steamAvailable}
              acquireVia={acquireVia}
              downloading={downloading}
              onSubscribe={onSubscribe}
              onUnsubscribe={onUnsubscribe}
              workshopTitles={workshopTitles}
            />
            <ModList
              title="Active"
              ids={active}
              mods={mods}
              selectedId={selectedId}
              onSelect={onSelectId}
              onActivate={deactivate}
              sortable
              onReorder={reorder}
              emptyText="No active mods"
              modColors={modColors}
              onSetColor={onSetColor}
              say={say}
              gameVersion={gameVersion}
              dependencyIds={dependencyIds}
              dependentIds={dependentIds}
              conflicts={validation.conflicts}
              issuesByMod={issuesByMod}
              onShowIssue={showIssue}
              steamAvailable={steamAvailable}
              acquireVia={acquireVia}
              downloading={downloading}
              onSubscribe={onSubscribe}
              onUnsubscribe={onUnsubscribe}
              workshopTitles={workshopTitles}
            />
          </main>
        )}
        <ActionsColumn
          busy={busy}
          noGame={noGame}
          dirty={dirty}
          paths={paths}
          activeCount={active.length}
          canRescan={!!(paths && paths.modsDir)}
          canSort={active.length > 0}
          problemCount={problems.length}
          warningCount={warningCount}
          errorCount={errorCount}
          onImport={openMenu('import')}
          onExport={openMenu('export')}
          onRescan={onRescan}
          onSort={onSort}
          onSave={onSave}
          syncing={syncing}
          onSync={syncToSteam}
          onShowScanIssues={() => setScanIssuesOpen(true)}
          onShowIssues={() => setIssuesOpen({})}
          onPush={onPush}
          onRun={onRun}
        />
      </div>
      <div className="action-divider" />
      <footer className={`statusbar ${status.kind}`}>
        <span className="status-text">{status.text}</span>
        {dl && <DownloadBar dl={dl} titles={workshopTitles} onToggle={onToggleDownloadPause} />}
      </footer>
      {issuesOpen && (
        <ValidationWindow
          issues={validation.issues}
          mods={mods}
          initialSeverity={issuesOpen.severity}
          initialKey={issuesOpen.key}
          onClose={closeIssues}
        />
      )}
      {scanIssuesOpen && <ScanIssuesWindow problems={problems} steamAvailable={steamAvailable} onClose={closeScanIssues} onIgnore={ignoreScanIssue} />}
      {settingsOpen && (
        <SettingsWindow
          paths={paths}
          busy={busy}
          acquireVia={acquireVia}
          acquireAuto={!ACQUIRE_MODES.includes(acquireSetting)}
          onSetAcquireVia={onSetAcquireVia}
          checkingMissing={checkingMissing}
          onCheckMissing={() => checkMissingWorkshop()}
          onAutodetect={onAutodetect}
          onBrowse={onBrowse}
          logPath={info && info.logPath}
          prevLogPath={info && info.prevLogPath}
          onOpenPath={onOpenPath}
          onClose={closeSettings}
        />
      )}
      {menu && <ContextMenu x={menu.x} y={menu.y} items={menuItems} onClose={closeMenu} />}
      {collectionOpen && (
        <CollectionDialog mods={mods} busy={busy} onImport={onCollectionImport} onCancel={() => setCollectionOpen(false)} />
      )}
      {dialog && (
        <NameDialog
          title={dialog.title}
          message={dialog.message}
          confirmLabel={dialog.confirmLabel}
          askName={dialog.askName !== false}
          toggleLabel={dialog.toggleLabel}
          confirmClass={dialog.confirmClass}
          placeholder={dialog.placeholder}
          busy={busy}
          error={dialogError}
          onConfirm={
            dialog.runConfirm
              ? () => {
                  setDialog(null);
                  launchNow();
                }
              : dialog.unsubscribe
                ? () => {
                    setDialog(null);
                    unsubscribeNow(dialog.unsubscribe);
                  }
                : dialog.removeDownload
                  ? () => {
                      setDialog(null);
                      removeDownloadNow(dialog.removeDownload);
                    }
                  : dialog.savePush
                    ? onSaveAndPush
                    : dialog.urlPrompt
                      ? onRentryConfirm
                      : onCreate
          }
          onCancel={() => {
            // New load order... from a collection: undo the import too, so a later
            // Save can't write the collection into the load order still open.
            if (dialog.revertOnCancel) {
              setHistory((h) => h.slice(0, -1)); // applyImport's undo entry
              showLists(mods, dialog.revertOnCancel);
            }
            setDialog(null);
            setDialogError(null);
          }}
        />
      )}
    </div>
  );
}
