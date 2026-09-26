'use strict';
// Steam Workshop subscribe/unsubscribe (PLAN.md item 4), main-process side.
// The Steamworks SDK (steamworks.js, a native addon) never runs in this
// process: every Steam call goes to a short-lived helper, lib/steamWorker.js,
// started with Electron's utilityProcess.
//
// Why: initializing the Steam client registers the calling process with Steam
// as "RimWorld, running". Done in VOLT's main process (round 1), Steam's own
// "Stop" killed VOLT itself, and the user showed as in-game until VOLT
// closed (steamworks.js has no shutdown). Now only the helper is registered,
// and only while an operation is in flight. A native crash in the SDK also
// takes down only the helper; it's reported as an ordinary error.
//
// One helper per operation, keyed by Workshop item id. The renderer drives
// each operation as a sequence of the existing IPC calls, so the boundaries
// are read from those calls (App.jsx onSubscribe / unsubscribeNow):
//   Subscribe:   subscribe(id)   starts a fresh helper, then installInfo(id)
//                polls reuse it. Ends when a status comes back installed.
//   Unsubscribe: unsubscribe(id) starts a fresh helper, then isSubscribed(id)
//                checks reuse it. Ends when isSubscribed comes back false.
//   Install wait: installInfo(id) with no operation in flight for that id
//                starts one (Sync to Steam's wait-for-install pass, after its
//                subscribe pass released the subscribe operation); the next
//                polls reuse it. Ends when a status comes back installed.
//   Any:         any error (SDK failure, helper crash, no answer) ends it, and
//                so does release(id) (Sync's subscribe pass, once an item's
//                subscription is verified: lists.js syncSteamCmdMods). The
//                renderer's own give-ups (timeout, "not subscribed" early
//                fail, verify retries exhausted) never reach here, so an
//                operation with no new call for IDLE_MS is ended too.
// isSubscribed and workshopItem with no operation in flight for that id run in
// a one-shot helper (started, asked, stopped).
//
// availability() never starts a helper: it checks the steam_appid.txt gate and
// that the steamworks.js package is installed (resolvable), without loading
// it. Whether Steam is running is reported by the first real action.
//
// Every failure becomes an Error with a user-readable message, which main.js's
// IPC wrapper turns into { ok: false, error }.

const path = require('node:path');
const paths = require('./paths');
const { log, clip } = require('./log');

const APP_ID = Number(paths.STEAM_APPID); // 294100
const WORKER_SCRIPT = path.join(__dirname, 'steamWorker.js');

const timing = {
  // One call's answer from the helper. subscribe/unsubscribe wait on a Steam
  // callback; a status check is immediate. Past this the operation is ended.
  jobTimeoutMs: 30_000,
  // No call for this long ends the operation. The renderer polls every 1-2 s
  // while it's still interested.
  idleMs: 10_000,
  // Wait this long for the helper to exit after 'shutdown', then kill() it.
  shutdownGraceMs: 2_000,
};

let forkImpl = null; // check-harness override for utilityProcess.fork
const live = new Set(); // every helper not yet exited
const ops = new Map(); // item id string -> { worker, idle, busy }

function errText(err) {
  return err && err.message ? err.message : String(err);
}

// Workshop ids are unsigned 64-bit, sent to the helper as a decimal string.
// BigInt return kept from round 1 (main.js builds the folder path from it).
function toItemId(id) {
  const s = String(id == null ? '' : id).trim();
  if (!/^\d{1,20}$/.test(s)) throw new Error(`Not a Steam Workshop item id: ${id}`);
  return BigInt(s);
}

function bindingMissing() {
  try {
    require.resolve('steamworks.js');
    return null;
  } catch (err) {
    return errText(err);
  }
}

// { available, reason }: whether Steam Workshop actions can be offered for this
// install. Starts no helper and loads no native code.
async function availability(gameDir) {
  if (!gameDir) return { available: false, reason: 'The RimWorld install folder is not set.' };
  if (!(await paths.hasSteamAppId(gameDir))) {
    return {
      available: false,
      reason: "This RimWorld install isn't a Steam build (no steam_appid.txt), so Steam Workshop actions are unavailable.",
    };
  }
  const missing = bindingMissing();
  if (missing) {
    return {
      available: false,
      reason: `The Steamworks library (steamworks.js) couldn't be loaded, so Steam Workshop actions are unavailable: ${missing}`,
    };
  }
  return { available: true, reason: null };
}

function forkWorker() {
  if (forkImpl) return forkImpl(WORKER_SCRIPT);
  const { app, utilityProcess } = require('electron');
  // Explicit cwd at APP-ROOT: SteamAPI_Init's breakpad bootstrap writes files
  // relative to cwd, and the inherited one sits under src/electron/ in dev,
  // which dev.js's watcher sees as a source change and restarts Electron.
  const { resolveAppRoot, GAME_SLUG } = require('./appRoot');
  const cwd = resolveAppRoot(app, GAME_SLUG);
  return utilityProcess.fork(WORKER_SCRIPT, [], { serviceName: 'volt-steam-worker', cwd });
}

// Starts one helper. Returns { send(action, id) -> Promise<value>, stop() ->
// Promise<void>, exited }. Once the helper is gone (stopped or crashed), every
// pending and later send rejects.
function startWorker() {
  let child;
  try {
    child = forkWorker();
  } catch (err) {
    const e = new Error(`Couldn't start the Steam helper process: ${errText(err)}`);
    log(`[steam] ${e.message}`);
    throw e;
  }
  log('[steam] helper process spawned');
  const pending = new Map(); // seq -> { resolve, reject, timer }
  let seq = 0;
  let dead = null; // Error every send rejects with once the helper is gone
  let stopping = false;
  let gone = false; // 'exit' seen
  let markExited;
  const exited = new Promise((resolve) => (markExited = resolve));

  const failAll = (err) => {
    for (const p of pending.values()) {
      clearTimeout(p.timer);
      p.reject(err);
    }
    pending.clear();
  };

  child.on('message', (msg) => {
    const p = msg && pending.get(msg.seq);
    if (!p) return;
    pending.delete(msg.seq);
    clearTimeout(p.timer);
    if (msg.ok) p.resolve(msg.value);
    else p.reject(new Error(msg.error || 'The Steam helper reported an unknown error.'));
  });
  child.on('exit', (code) => {
    if (!dead) {
      dead = new Error(
        `The Steam helper process stopped unexpectedly (exit code ${code}) - Steam may have closed it, or the Steamworks library crashed.`,
      );
    }
    log(`[steam] helper process exited (code ${code}): ${dead.message}`);
    failAll(dead);
    gone = true;
    live.delete(handle);
    markExited();
  });
  // UtilityProcess is an EventEmitter: an 'error' with no listener would throw
  // in the main process. The 'exit' that follows does the reporting.
  child.on('error', (...info) => {
    console.error('[steam] helper process error:', ...info);
    log(`[steam] helper process error: ${info.map(String).join(' ')}`);
  });

  function send(action, id) {
    if (dead) return Promise.reject(dead);
    return new Promise((resolve, reject) => {
      const s = ++seq;
      const timer = setTimeout(() => {
        pending.delete(s);
        reject(new Error(`Steam didn't answer within ${Math.round(timing.jobTimeoutMs / 1000)} seconds.`));
      }, timing.jobTimeoutMs);
      pending.set(s, { resolve, reject, timer });
      try {
        child.postMessage({ seq: s, action, id });
      } catch (err) {
        pending.delete(s);
        clearTimeout(timer);
        reject(new Error(`Couldn't reach the Steam helper process: ${errText(err)}`));
      }
    });
  }

  // Ask the helper to exit; kill() it if it hasn't within the grace period.
  // An already-exited helper (e.g. crashed) is left alone.
  function stop() {
    if (!stopping) {
      stopping = true;
      if (!dead) dead = new Error('The Steam operation was ended.');
      failAll(dead);
      if (gone) return exited;
      try {
        child.postMessage({ action: 'shutdown' });
      } catch {
        // already gone or unreachable: the kill below covers it
      }
      const t = setTimeout(() => {
        try {
          child.kill();
        } catch {
          // already exited
        }
      }, timing.shutdownGraceMs);
      exited.then(() => clearTimeout(t));
    }
    return exited;
  }

  const handle = { send, stop, exited };
  live.add(handle);
  return handle;
}

function endOp(key, op) {
  clearTimeout(op.idle);
  if (ops.get(key) === op) ops.delete(key);
  return op.worker.stop();
}

// A new operation on this id: any earlier one still around is ended first.
function beginOp(key) {
  const prev = ops.get(key);
  if (prev) endOp(key, prev);
  const op = { worker: startWorker(), idle: null, busy: 0 }; // busy: calls awaiting an answer
  ops.set(key, op);
  return op;
}

// Runs one action in the helper for `id`. fresh: starts a new operation;
// otherwise joins the operation in flight for that id, or when there's none
// starts one (begin) or uses a one-shot helper (the default). done(value): true
// when this answer completes the operation.
// Every call is logged: action, item id, which helper it ran in, and the real
// answer (status object / boolean) or error (CLAUDE.md §10).
async function job(gameDir, id, action, { fresh = false, begin = false, done = () => false } = {}) {
  const key = toItemId(id).toString();
  const a = await availability(gameDir);
  if (!a.available) {
    log(`[steam] ${action} ${key} refused: ${a.reason}`);
    throw new Error(a.reason);
  }

  if (!fresh && !ops.has(key) && !begin) {
    log(`[steam] ${action} ${key} (one-shot helper)...`);
    const worker = startWorker();
    try {
      const value = await worker.send(action, key);
      log(`[steam] ${action} ${key} -> ${clip(value)}`);
      return value;
    } catch (err) {
      log(`[steam] ${action} ${key} failed: ${errText(err)}`);
      throw err;
    } finally {
      worker.stop();
    }
  }

  const starts = fresh || !ops.has(key);
  log(`[steam] ${action} ${key} (${starts ? 'new operation' : 'operation in flight'})...`);
  const op = starts ? beginOp(key) : ops.get(key);
  clearTimeout(op.idle);
  op.busy++;
  try {
    const value = await op.worker.send(action, key);
    op.busy--;
    const finished = done(value);
    log(`[steam] ${action} ${key} -> ${clip(value)}${finished ? ' (operation complete)' : ''}`);
    if (finished) endOp(key, op);
    else if (!op.busy && ops.get(key) === op) {
      op.idle = setTimeout(() => {
        log(`[steam] operation on ${key} ended: no call for ${timing.idleMs / 1000} s`);
        endOp(key, op);
      }, timing.idleMs);
      if (op.idle.unref) op.idle.unref();
    }
    return value;
  } catch (err) {
    op.busy--;
    log(`[steam] ${action} ${key} failed, operation ended: ${errText(err)}`);
    endOp(key, op);
    throw err;
  }
}

// Subscribe and ask Steam to download it (high priority). Returns the item
// status; poll installInfo() until status.installed.
const subscribe = (gameDir, id) => job(gameDir, id, 'subscribe', { fresh: true, done: (st) => st.installed });
const installInfo = (gameDir, id) => job(gameDir, id, 'installInfo', { begin: true, done: (st) => st.installed });
// Unsubscribe. A resolved call isn't proof it took: callers verify with
// isSubscribed(), which ends the operation once it reports false.
const unsubscribe = (gameDir, id) => job(gameDir, id, 'unsubscribe', { fresh: true });
const isSubscribed = (gameDir, id) => job(gameDir, id, 'isSubscribed', { done: (sub) => !sub });
// The item's listing via the logged-in Steam client: { found, title, ... }.
// Scan Issues' fallback when the keyless Web API returns not found.
const workshopItem = (gameDir, id) => job(gameDir, id, 'workshopItem');

// Ends the operation in flight on `id`, if any, without waiting for its helper
// to exit. Sync to Steam's subscribe pass calls it once an item's subscription
// is verified: that pass subscribes a whole list back to back, and leaving each
// helper for the IDLE_MS timeout would pile up dozens of live helpers. An
// operation with a call still awaiting an answer is left alone. Returns
// whether one was ended.
function release(id) {
  const key = toItemId(id).toString();
  const op = ops.get(key);
  if (!op || op.busy) {
    log(`[steam] release ${key}: ${op ? 'a call is still in flight, operation kept' : 'no operation in flight'}`);
    return false;
  }
  log(`[steam] release ${key}: operation ended by the caller`);
  endOp(key, op);
  return true;
}

// Ends every operation and stops every helper (app quit).
function stopAll() {
  for (const [key, op] of [...ops]) endOp(key, op);
  return Promise.all([...live].map((w) => w.stop()));
}

module.exports = {
  APP_ID,
  availability,
  subscribe,
  unsubscribe,
  installInfo,
  isSubscribed,
  workshopItem,
  release,
  toItemId,
  stopAll,
  // check harness only
  _test: {
    setFork: (fn) => (forkImpl = fn),
    timing,
    liveCount: () => live.size,
    opIds: () => [...ops.keys()],
  },
};
