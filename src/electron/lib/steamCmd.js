'use strict';
// SteamCMD downloads (PLAN.md item 4, "SteamCMD as the primary acquisition
// mechanism"): Workshop items are fetched with Valve's command-line client,
// logged in anonymously, so no Steam client, no login and no "RimWorld is
// running" flash. Steamworks (lib/steam.js) stays for the later sync step.
//
// SteamCMD itself works under APP-ROOT, never in the real Steam library:
//   <appRoot>/steamcmd/          steamcmd.exe (fetched from Valve on first use)
//                                plus the files it self-updates beside it
//   <appRoot>/steamcmd-library/  force_install_dir, SteamCMD's own cache; items
//                                land in steamapps/workshop/content/294100/<id>
// Pointing force_install_dir at the real library would let SteamCMD rewrite
// the desktop client's own bookkeeping (RimSort avoids it the same way).
//
// RimWorld only loads Data, Mods and Steam-subscribed items, so each finished
// item is then COPIED (the cache stays, so SteamCMD doesn't re-fetch it) into
// <game>/Mods/<id> with a MARKER file inside. The marker records which
// acquisition mode made the copy (SCOPE.md §2a, MARKER_MODES below) and the
// scan tags the folder's source from it (mods.js): 'steamcmd' (a temporary
// copy Sync to Steam later replaces) or 'gog' (the mod's permanent home).
// Never into the real Workshop folder: Steam manages that one's contents.
//
// downloadItems' per-item status is parsed from SteamCMD's output and is
// best effort only; the caller rescans and treats "the mod is on disk now" as
// the real answer (App.jsx).
//
// Every failure becomes an Error with a user-readable message, which main.js's
// IPC wrapper turns into { ok: false, error }.

const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const { StringDecoder } = require('node:string_decoder');
const path = require('node:path');
const zlib = require('node:zlib');
const { spawn } = require('node:child_process');
const { exists, isDir, removeTreeBestEffort, stripBom } = require('./fsutil');
const { STEAM_APPID } = require('./paths');
const { log, clip } = require('./log');

const STEAMCMD_ZIP_URL = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip';
const EXE = 'steamcmd.exe';
// Marker file inside <game>/Mods/<id>: a small JSON payload,
// {"mode":"steamcmd"|"gog","copiedAt":"<ISO time>"} (markerText). Before the
// mode field existed (v0.3.9-v0.4.1) it held just an ISO timestamp line or
// nothing; readMarkerMode reads those as 'steamcmd'.
const MARKER = '.volt-steamcmd';
// Pre-0.4.10 name of MARKER. Only readMarkerMode knows it: it renames a leftover
// one to MARKER in place, so nothing else ever needs to check both names.
const LEGACY_MARKER = '.rwjsc-steamcmd';
// Acquisition modes a marker can record (SCOPE.md §2a; settings.json
// steamAcquireVia minus 'steamworks', which never touches Mods):
//   'steamcmd' - a temporary copy: Sync to Steam subscribes it for real, then
//                deletes this copy once Steam's own download is on disk.
//   'gog'      - a permanent copy (GOG install, or chosen): no Steam
//                subscription to graduate into, so Sync never touches it.
// 'pinned' is reserved for future per-load-order pinning, with its own marker
// file (SCOPE.md §2a) - deliberately not one of these.
const MARKER_MODES = ['steamcmd', 'gog'];

function markerText(mode) {
  return `${JSON.stringify({ mode, copiedAt: new Date().toISOString() })}\n`;
}

// A marker's mode from its text: 'gog' only when the JSON payload says so;
// anything else - an older marker (timestamp line or empty), unparseable text,
// an unknown mode - is 'steamcmd', so a pre-mode-field copy (already on real
// users' disks) keeps behaving exactly as before and never throws.
function parseMarkerMode(text) {
  try {
    const v = JSON.parse(stripBom(String(text == null ? '' : text)));
    if (v && typeof v === 'object' && v.mode === 'gog') return 'gog';
  } catch {
    // legacy / unparseable: 'steamcmd' below
  }
  return 'steamcmd';
}

// Mode of <dir>/MARKER: null when there's no marker (not VOLT's copy), else
// parseMarkerMode's answer. A marker that exists but can't be read also counts
// as 'steamcmd' (it's still ours). A LEGACY_MARKER with no MARKER beside it is
// renamed to MARKER first (self-healing migration of pre-0.4.10 copies on the
// user's disk); a failed rename is logged and the scan carries on.
async function readMarkerMode(dir) {
  const legacy = path.join(dir, LEGACY_MARKER);
  if ((await exists(legacy)) && !(await exists(path.join(dir, MARKER)))) {
    try {
      await fs.rename(legacy, path.join(dir, MARKER));
      log(`[steamcmd] migrated legacy ${LEGACY_MARKER} marker in ${dir}`);
    } catch (err) {
      log(`[steamcmd] couldn't migrate legacy ${LEGACY_MARKER} marker in ${dir}: ${err && err.message ? err.message : err}`);
    }
  }
  let text;
  try {
    text = await fs.readFile(path.join(dir, MARKER), 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT' || err.code === 'ENOTDIR') return null;
    return 'steamcmd';
  }
  return parseMarkerMode(text);
}

const timing = {
  fetchTimeoutMs: 60_000,
  // One SteamCMD run (a whole collection included). Past this it's killed; the
  // caller's rescan still picks up whatever finished.
  runTimeoutMs: 30 * 60_000,
  // How often a download run's console log is read for live lines
  // (createLogTail); RimSort's interval.
  logPollMs: 150,
};
// Check-harness seams (no real Windows / SteamCMD here; removeTree: a locked
// file can't be faked portably, so deleteItem's partial-delete path is tested
// through this).
const env = { platform: process.platform, spawn, removeTree: removeTreeBestEffort };

const toolDir = (appRoot) => path.join(appRoot, 'steamcmd');
const libraryDir = (appRoot) => path.join(appRoot, 'steamcmd-library');
const contentDir = (appRoot) => path.join(libraryDir(appRoot), 'steamapps', 'workshop', 'content', STEAM_APPID);
// SteamCMD's own console log: it writes this by itself, no flag needed.
const consoleLog = (appRoot) => path.join(toolDir(appRoot), 'logs', 'console_log.txt');

function errText(err) {
  return err && err.message ? err.message : String(err);
}

function toWorkshopId(id) {
  const s = String(id == null ? '' : id).trim();
  if (!/^\d{1,20}$/.test(s)) throw new Error(`Not a Steam Workshop item id: ${id}`);
  return s;
}

// Minimal .zip reader (stored + deflate entries, via the central directory):
// enough for Valve's steamcmd.zip without a new dependency. Refuses any entry
// that would land outside destDir.
async function unzipTo(buf, destDir) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 0xffff); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error('not a zip file');
  const count = buf.readUInt16LE(eocd + 10);
  let p = buf.readUInt32LE(eocd + 16);
  const root = path.resolve(destDir);
  await fs.mkdir(root, { recursive: true });
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error('corrupt zip directory');
    const method = buf.readUInt16LE(p + 10);
    const size = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const next = p + 46 + nameLen + buf.readUInt16LE(p + 30) + buf.readUInt16LE(p + 32);
    const name = buf.toString('utf8', p + 46, p + 46 + nameLen);
    const local = buf.readUInt32LE(p + 42);
    p = next;
    const target = path.resolve(root, name);
    if (target !== root && !target.startsWith(root + path.sep)) throw new Error(`unsafe path in zip: ${name}`);
    if (name.endsWith('/')) {
      await fs.mkdir(target, { recursive: true });
      continue;
    }
    if (buf.readUInt32LE(local) !== 0x04034b50) throw new Error('corrupt zip entry');
    const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
    const raw = buf.subarray(start, start + size);
    let data;
    if (method === 0) data = raw;
    else if (method === 8) data = zlib.inflateRawSync(raw);
    else throw new Error(`unsupported zip compression (${method}) for ${name}`);
    await fs.mkdir(path.dirname(target), { recursive: true });
    await fs.writeFile(target, data);
  }
}

// Live lines for a download run, tailed from SteamCMD's own console log
// (consoleLog(): <appRoot>/steamcmd/logs/console_log.txt) rather than its
// stdout. Why - don't "simplify" this back to reading the pipe: on Windows
// SteamCMD fully buffers its stdout when it's a pipe rather than a real
// console, so its "Update state ... progress" and "Success. Downloaded item N"
// lines only reached us when the process exited (seen on real hardware with
// v0.4.0: the status-bar row sat at 0% until the whole run ended). The log
// file is written to disk as SteamCMD goes, however its stdout is buffered.
// The approach is RimSort's (its SteamcmdInterface tails the same file on a
// 150 ms timer on Windows); it replaced v0.4.1's workaround of splitting one
// download into up to 10 SteamCMD processes so each exit forced a flush.
// SteamCMD appends to this file across runs and never truncates it, so the
// tail starts at the file's size when it's created (right before the spawn):
// an earlier run's lines are never re-read. No file yet (first run, before
// SteamCMD has created logs/) = nothing to read this time, not an error.
// Returns poll(final): passes each complete line appended since the last poll
// to onLine, split on \r as well as \n (SteamCMD redraws its progress line with
// a bare \r); a trailing partial line waits for the next poll, and poll(true)
// - the last one, after the process exits - passes it too.
// ponytail: console_log.txt grows forever over the app's lifetime - SteamCMD
// never rotates it and neither does this (RimSort accepts the same). Rotate or
// truncate it before a run, like volt.log's one-level rotation (log.js), if
// its size is ever reported as a real problem.
function createLogTail(file, onLine) {
  const sizeNow = () => {
    try {
      return fsSync.statSync(file).size;
    } catch {
      return 0; // not there yet
    }
  };
  let offset = sizeNow();
  let rest = '';
  const decoder = new StringDecoder('utf8'); // a character split across two reads stays whole
  let warned = false;
  return (final = false) => {
    let text = '';
    try {
      const end = sizeNow();
      if (end < offset) offset = 0; // replaced or emptied under us: read the new file from its start
      if (end > offset) {
        const buf = Buffer.alloc(end - offset);
        const fd = fsSync.openSync(file, 'r');
        try {
          const n = fsSync.readSync(fd, buf, 0, buf.length, offset);
          offset += n;
          text = decoder.write(buf.subarray(0, n));
        } finally {
          fsSync.closeSync(fd);
        }
      }
    } catch (err) {
      if (err.code !== 'ENOENT' && !warned) {
        warned = true;
        log(`[steamcmd] couldn't read ${file} for live progress (${errText(err)}); retrying on every poll (the run's result doesn't depend on it)`);
      }
    }
    if (final) text += decoder.end();
    const parts = (rest + text).split(/[\r\n]+/);
    rest = final ? '' : parts.pop();
    for (const l of parts) if (l) onLine(l);
  };
}

// Runs steamcmd.exe; resolves { code, signal, output } (stdout + stderr) once
// it exits, rejects only if it can't be started. stdin is closed, so a prompt
// can never hang it. `output` is the run's ground truth (parseDownloadOutput):
// by the time the process has exited, every byte of its pipes has arrived.
// onLine (optional, with logFile): gets each line live, from logFile tailed
// every timing.logPollMs plus once more at exit (createLogTail; why not the
// pipes: its comment). The pipes only ever fill `output`.
// cancellable: this is the run cancelCurrent() kills (the download run; never
// the first-launch self-update, which a kill could leave half-applied).
function runSteamCmd(exe, args, { onLine, logFile, cancellable = false } = {}) {
  return new Promise((resolve, reject) => {
    let output = '';
    // Created before the spawn, so its start offset is the log's size now.
    const poll = onLine && logFile ? createLogTail(logFile, onLine) : null;
    let child;
    try {
      child = env.spawn(exe, args, {
        cwd: path.dirname(exe),
        windowsHide: true,
        stdio: ['ignore', 'pipe', 'pipe'],
        timeout: timing.runTimeoutMs,
      });
    } catch (err) {
      reject(new Error(`Couldn't start SteamCMD (${errText(err)}).`));
      return;
    }
    if (cancellable) currentChild = child;
    let timer = poll ? setInterval(() => poll(), timing.logPollMs) : null;
    const endTail = () => {
      if (!timer) return;
      clearInterval(timer);
      timer = null;
      poll(true); // whatever SteamCMD wrote after the last tick
    };
    const collect = (d) => {
      output += d;
    };
    child.stdout.on('data', collect);
    child.stderr.on('data', collect);
    child.on('error', (e) => {
      if (currentChild === child) currentChild = null;
      endTail();
      reject(new Error(`Couldn't start SteamCMD (${errText(e)}).`));
    });
    child.on('close', (code, signal) => {
      if (currentChild === child) currentChild = null;
      endTail();
      resolve({ code, signal, output: output.replace(/\r/g, '') });
    });
  });
}

// Live per-line parser for a download run (the status-bar row, App.jsx), fed
// the console log's lines (createLogTail).
// Emits onEvent({ type: 'progress', id, percent, bytesDownloaded, bytesTotal,
// speedBytesPerSec }) and onEvent({ type: 'item-done', id, ok, message }).
// Only a live tap: parseDownloadOutput on the full output stays the source of
// truth for the run's result.
// The progress line carries no item id. INFERRED mapping (not reported by
// SteamCMD, unconfirmed on real hardware): the runscript's
// workshop_download_item commands run strictly in order, one at a time, so the
// item downloading now is the first id in `wids` not yet resolved by a
// Success/ERROR line. `ptr` tracks it.
// Speed = byte delta / time delta between the item's two latest samples (no
// smoothing); null for an item's first sample.
function createProgressParser(wids, onEvent, now = Date.now) {
  let ptr = 0;
  let last = null; // latest sample for wids[ptr]: { bytes, t }
  return (line) => {
    const done = /Success\. Downloaded item (\d+)/.exec(line);
    const fail = !done && /ERROR! Download item (\d+) failed \(([^)]*)\)/.exec(line);
    if (done || fail) {
      const id = (done || fail)[1];
      const i = wids.indexOf(id, ptr);
      if (i >= 0) {
        ptr = i + 1;
        last = null;
      }
      onEvent({ type: 'item-done', id, ok: !!done, message: fail ? fail[2] : null });
      return;
    }
    const p = /Update state \(0x[0-9a-f]+\) downloading, progress: ([\d.]+) \((\d+) \/ (\d+)\)/.exec(line);
    if (!p || ptr >= wids.length) return;
    const bytes = Number(p[2]);
    const t = now();
    const speed = last && t > last.t && bytes >= last.bytes ? (bytes - last.bytes) / ((t - last.t) / 1000) : null;
    last = { bytes, t };
    onEvent({ type: 'progress', id: wids[ptr], percent: Number(p[1]), bytesDownloaded: bytes, bytesTotal: Number(p[3]), speedBytesPerSec: speed });
  };
}

// <appRoot>/steamcmd/steamcmd.exe, fetched from Valve's CDN and unpacked on
// first use. Unpacked into a side folder and renamed into place, so a failed
// fetch never leaves a half-installed copy that the exists check would trust.
async function ensureSteamCmd(appRoot) {
  if (env.platform !== 'win32') {
    throw new Error('Downloading mods with SteamCMD is only supported on Windows for now. Switch "Download mods via" in Settings > Steam to "Steam client directly".');
  }
  const dir = toolDir(appRoot);
  const exe = path.join(dir, EXE);
  if (await exists(exe)) return exe;
  log(`[steamcmd] ${exe} not found, fetching ${STEAMCMD_ZIP_URL}`);
  let buf;
  try {
    const res = await fetch(STEAMCMD_ZIP_URL, { signal: AbortSignal.timeout(timing.fetchTimeoutMs) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    buf = Buffer.from(await res.arrayBuffer());
  } catch (err) {
    log(`[steamcmd] fetch failed: ${errText(err)}`);
    throw new Error(`Couldn't download SteamCMD from Valve (${errText(err)}). Check your internet connection.`);
  }
  const partial = `${dir}.partial`;
  try {
    await fs.rm(partial, { recursive: true, force: true });
    await unzipTo(buf, partial);
    if (!(await exists(path.join(partial, EXE)))) throw new Error(`no ${EXE} inside`);
    await fs.rm(dir, { recursive: true, force: true });
    await fs.rename(partial, dir);
  } catch (err) {
    await fs.rm(partial, { recursive: true, force: true }).catch(() => {});
    log(`[steamcmd] unpack failed: ${errText(err)}`);
    throw new Error(`Couldn't unpack SteamCMD into ${dir} (${errText(err)}).`);
  }
  // First launch: SteamCMD updates itself (tens of MB) before it will do
  // anything. Its exit code here is often non-zero, so it isn't checked; the
  // real download run reports any failure.
  log(`[steamcmd] installed into ${dir}; first-run self-update: ${exe} +quit`);
  const first = await runSteamCmd(exe, ['+quit']);
  log(`[steamcmd] self-update exited (code ${first.code}, signal ${first.signal})`);
  return exe;
}

// Best-effort per-item status from SteamCMD's output: ok true/false when it
// printed a line for the item, null when it didn't. `error` is the last
// error-looking line (login failure etc.), if any.
function parseDownloadOutput(output, ids) {
  const status = new Map();
  for (const m of output.matchAll(/Success\. Downloaded item (\d+)/g)) status.set(m[1], { ok: true, message: null });
  for (const m of output.matchAll(/ERROR! Download item (\d+) failed \(([^)]*)\)/g)) status.set(m[1], { ok: false, message: m[2] });
  const errors = output.split('\n').filter((l) => /\b(error|failed)\b/i.test(l));
  return {
    results: ids.map((id) => ({ id, ...(status.get(id) || { ok: null, message: null }) })),
    error: errors.length ? errors[errors.length - 1].trim() : null,
  };
}

// Copies one downloaded item into <modsDir>/<id>, marker first (recording
// `mode`, MARKER_MODES) so even a half-finished copy is recognisably ours and
// can be replaced next time. An existing folder without the marker is
// someone's own mod: left alone. A marked one is replaced, marker included, so
// a re-download in another mode takes that mode.
async function installIntoMods(src, modsDir, id, mode) {
  const dest = path.join(modsDir, id);
  if (await exists(dest)) {
    if (!(await exists(path.join(dest, MARKER)))) throw new Error(`${dest} already exists and wasn't downloaded by VOLT, so it was left alone`);
    await fs.rm(dest, { recursive: true, force: true });
  }
  await fs.mkdir(dest, { recursive: true });
  await fs.writeFile(path.join(dest, MARKER), markerText(mode));
  await fs.cp(src, dest, { recursive: true });
  return dest;
}

// One SteamCMD run at a time: two instances sharing the same install dir would
// fight over its lock. ponytail: single global queue; fine for one app window.
let chain = Promise.resolve();
function queued(fn) {
  const p = chain.then(fn);
  chain = p.catch(() => {});
  return p;
}

// Pause (App.jsx status-bar row): cancelCurrent() kills the running download
// and cancels every downloadItems call already waiting in the queue. Each call
// remembers cancelEpoch when it's made; a bump since then means "cancelled by
// the user" (a kill by the run timeout doesn't bump it, so that stays an error).
let currentChild = null; // the running download's steamcmd.exe, if any
let cancelEpoch = 0;
let inFlight = 0; // downloadItems calls queued or running

function cancelCurrent() {
  if (!inFlight) {
    log('[steamcmd] cancel requested: no download running, nothing to do');
    return false;
  }
  cancelEpoch++;
  const child = currentChild;
  const killed = child ? child.kill() : false;
  log(`[steamcmd] cancel requested by user: ${inFlight} download call(s) in flight; ` +
    (child ? `killing steamcmd.exe (pid ${child.pid}) -> kill() returned ${killed}` : 'no steamcmd.exe running yet (fetch/self-update/queue), cancelled before it starts'));
  return true;
}

// Downloads Workshop items (ids: decimal strings) in ONE SteamCMD session via
// a runscript, so a whole collection is one process. The script file (not
// +command args) keeps a big collection clear of Windows' command-line length
// limit. Every item SteamCMD explicitly reported as downloaded ("Success.
// Downloaded item N") and that is in its cache is then copied into modsDir
// (<game>/Mods); a failed copy turns that item's ok to false with the reason.
// An unreported item is never copied: SteamCMD creates its content folder
// early, so a run killed mid-item (pause, timeout) can leave a half-download
// there. onEvent (optional) gets live progress: createProgressParser over the
// lines createLogTail reads from SteamCMD's console log while it runs (why
// not its stdout: createLogTail's comment). Resolves
// { contentDir, exitCode, results: [{ id, ok, message, path? }], error }, plus
// cancelled: true when cancelCurrent() stopped it (results = what finished
// before the kill). mode (MARKER_MODES, default 'steamcmd'): what each copy's
// marker records - the renderer passes its acquisition setting (App.jsx
// downloadViaSteamCmd), so a GOG-mode download is tagged permanent.
async function downloadItems(appRoot, ids, modsDir, onEvent, mode = 'steamcmd') {
  if (!Array.isArray(ids) || !ids.length) throw new Error('No Workshop items to download.');
  if (!modsDir) throw new Error('RimWorld install folder is not set.');
  if (!MARKER_MODES.includes(mode)) throw new Error(`Unknown download mode: ${mode}`);
  const wids = [...new Set(ids.map(toWorkshopId))];
  const epoch = cancelEpoch;
  const cancelled = () => epoch !== cancelEpoch;
  inFlight++;
  try {
    return await queued(async () => {
      if (cancelled()) {
        log(`[steamcmd] download of ${wids.length} item(s) cancelled by the user before it started`);
        return { contentDir: contentDir(appRoot), exitCode: null, ...parseDownloadOutput('', wids), cancelled: true };
      }
      const exe = await ensureSteamCmd(appRoot);
      if (cancelled()) {
        log(`[steamcmd] download of ${wids.length} item(s) cancelled by the user before SteamCMD ran`);
        return { contentDir: contentDir(appRoot), exitCode: null, ...parseDownloadOutput('', wids), cancelled: true };
      }
      await fs.mkdir(libraryDir(appRoot), { recursive: true });
      const script = path.join(toolDir(appRoot), 'volt-download.txt');
      const scriptText = [
        `force_install_dir "${libraryDir(appRoot)}"`,
        'login anonymous',
        ...wids.map((id) => `workshop_download_item ${STEAM_APPID} ${id}`),
        'quit',
        '',
      ].join('\n');
      await fs.writeFile(script, scriptText);
      log(`[steamcmd] running: "${exe}" +runscript "${script}" (${wids.length} item(s), mode '${mode}': copies marked ${mode === 'gog' ? 'permanent' : 'temporary, for Sync to Steam'}); live progress tailed from ${consoleLog(appRoot)} ` +
        `every ${timing.logPollMs} ms; script:\n${clip(scriptText)}`);
      // Live events: every item-done logged; progress logged once per item
      // (first sample, with its size) - per-sample lines would flood the log.
      const logged = new Set();
      const emit = (ev) => {
        if (ev.type === 'item-done') {
          log(`[steamcmd] live: item ${ev.id} ${ev.ok ? 'downloaded' : `FAILED (${ev.message})`}`);
        } else if (!logged.has(ev.id)) {
          logged.add(ev.id);
          log(`[steamcmd] live: first progress line, attributed to item ${ev.id} (inferred: next unresolved id in order): ` +
            `${ev.percent}% (${ev.bytesDownloaded} / ${ev.bytesTotal} bytes)`);
        }
        if (onEvent) {
          try {
            onEvent(ev);
          } catch (err) {
            log(`[steamcmd] live progress callback threw: ${errText(err)}`);
          }
        }
      };
      const run = await runSteamCmd(exe, ['+runscript', script], {
        onLine: createProgressParser(wids, emit),
        logFile: consoleLog(appRoot),
        cancellable: true,
      });
      // Tail of the output: the per-item lines and any error are near the end.
      const tail = run.output.length > 4000 ? `…[${run.output.length - 4000} earlier chars omitted]${run.output.slice(-4000)}` : run.output;
      log(`[steamcmd] exited (code ${run.code}, signal ${run.signal}); output:\n${tail.trim()}`);
      const parsed = parseDownloadOutput(run.output, wids);
      const userCancelled = !!run.signal && cancelled();
      const anyReported = parsed.results.some((r) => r.ok !== null);
      if (userCancelled) {
        log(`[steamcmd] run stopped by the user (pause); ${parsed.results.filter((r) => r.ok === true).length} of ${wids.length} item(s) had finished`);
      } else if (run.signal && !anyReported) {
        throw new Error(`SteamCMD didn't finish within ${timing.runTimeoutMs / 60_000} minutes and was stopped.`);
      } else if (run.code !== 0 && !anyReported) {
        throw new Error(`SteamCMD failed (exit code ${run.code})${parsed.error ? `: ${parsed.error}` : ''}.`);
      }
      await fs.mkdir(modsDir, { recursive: true });
      for (const r of parsed.results) {
        const src = path.join(contentDir(appRoot), r.id);
        if (r.ok !== true || !(await isDir(src))) continue;
        try {
          r.path = await installIntoMods(src, modsDir, r.id, mode);
        } catch (err) {
          r.ok = false;
          r.message = `couldn't copy it into ${modsDir}: ${errText(err)}`;
        }
      }
      for (const r of parsed.results) {
        log(`[steamcmd] item ${r.id}: ${r.ok === true ? 'ok' : r.ok === false ? 'FAILED' : 'not reported (not copied)'}` +
          `${r.message ? ` (${r.message})` : ''}${r.path ? ` -> ${r.path}` : ''}`);
      }
      if (parsed.error) log(`[steamcmd] last error line in output: ${parsed.error}`);
      return { contentDir: contentDir(appRoot), exitCode: run.code, ...parsed, ...(userCancelled ? { cancelled: true } : {}) };
    });
  } finally {
    inFlight--;
  }
}

// Best-effort delete of a SteamCMD mod's folder (its scanned mod.path):
// Unsubscribe/Remove on a SteamCMD-downloaded mod (either marker mode - the
// user asked), and a 'steamcmd' copy once Sync to Steam has really subscribed
// it (Sync never passes a 'gog' one: lists.js syncSteamCmdMods only picks
// source 'steamcmd'). The path comes from the renderer, so it must be a
// direct child of modsDir holding our MARKER - nothing else can be deleted.
// SteamCMD's own cache copy is left alone.
// Resolves { path, removed, skipped, gone } (fsutil removeTreeBestEffort) and
// never throws for a locked file: CALLERS MUST CHECK `gone` - false means the
// folder is still on disk (skipped lists what couldn't be removed), i.e. NOT
// deleted, whatever else happened. On a partial delete the marker is put back
// if it was among the files removed (it sorts first, so it usually is): the
// leftover then still scans as ours, so the next Sync / Remove finds it and
// this function still accepts it.
async function deleteItem(modsDir, modPath) {
  const dir = typeof modPath === 'string' && modPath ? path.resolve(modPath) : '';
  if (!modsDir || !dir || path.dirname(dir) !== path.resolve(modsDir) || !(await exists(path.join(dir, MARKER)))) {
    throw new Error(`Not a SteamCMD-downloaded mod folder: ${modPath}`);
  }
  const marker = path.join(dir, MARKER);
  let markerBody = null;
  try {
    markerBody = await fs.readFile(marker);
  } catch {
    // vanished since the check above: nothing to restore
  }
  const r = await env.removeTree(dir);
  let restored = '';
  if (!r.gone && markerBody && (await isDir(dir)) && !(await exists(marker))) {
    try {
      await fs.writeFile(marker, markerBody);
      restored = '; marker restored so the leftover stays recognisably VOLT\'s (retried by the next Sync / Remove)';
    } catch (err) {
      restored = `; couldn't restore the marker (${errText(err)}) - the leftover will scan as a hand-installed mod`;
    }
  }
  if (r.gone) log(`[steamcmd] deleted ${dir} (${r.removed} file(s) removed)`);
  else {
    log(`[steamcmd] delete of ${dir} INCOMPLETE - folder still on disk: ${r.removed} file(s) removed, ${r.skipped.length} couldn't be ` +
      `(locked or in use?): ${clip(r.skipped)}${restored}`);
  }
  return { path: dir, ...r };
}

module.exports = {
  STEAMCMD_ZIP_URL,
  MARKER,
  LEGACY_MARKER,
  MARKER_MODES,
  parseMarkerMode,
  readMarkerMode,
  timing,
  env,
  toolDir,
  libraryDir,
  contentDir,
  consoleLog,
  unzipTo,
  ensureSteamCmd,
  parseDownloadOutput,
  createLogTail,
  createProgressParser,
  downloadItems,
  cancelCurrent,
  deleteItem,
};
