'use strict';
// Steamworks helper process (PLAN.md item 4). Never require()d by the main
// process: lib/steam.js runs it with Electron's utilityProcess.fork, one fresh
// instance per Workshop operation, and kills it when the operation ends.
//
// Why a separate process: steamworks.js's init(294100) registers the calling
// process with Steam as "RimWorld, running". Done in VOLT's own main process,
// Steam's "Stop" then killed VOLT itself, and the user showed as in-game for
// as long as VOLT stayed open. Here only this short-lived helper is ever
// registered, and a native crash inside the SDK takes down only the helper.
//
// Messages (process.parentPort, structured clone):
//   in:  { seq, action, id }  action: subscribe | unsubscribe | installInfo | isSubscribed | workshopItem
//        { action: 'shutdown' }  -> exits
//   out: { seq, ok: true, value } | { seq, ok: false, error }
// id is a Workshop item id as a decimal string (already validated main-side;
// re-checked here). value holds no BigInts.
//
// The Steam client is initialized on the first job and kept for this worker's
// lifetime (every poll of one operation reuses it). A failed init isn't
// cached, so a retry within the same operation tries again.

const APP_ID = 294100; // RimWorld; must equal paths.STEAM_APPID (the check harness asserts it)

// EItemState bit flags (Steamworks SDK, isteamugc.h). steamworks.js's
// workshop.state() returns the raw bitmask and exports no runtime enum for it.
const ITEM_STATE = {
  SUBSCRIBED: 1,
  LEGACY_ITEM: 2,
  INSTALLED: 4,
  NEEDS_UPDATE: 8,
  DOWNLOADING: 16,
  DOWNLOAD_PENDING: 32,
};

function errText(err) {
  return err && err.message ? err.message : String(err);
}

// Workshop ids are unsigned 64-bit; steamworks.js takes them as BigInt.
function toItemId(id) {
  const s = String(id == null ? '' : id).trim();
  if (!/^\d{1,20}$/.test(s)) throw new Error(`Not a Steam Workshop item id: ${id}`);
  return BigInt(s);
}

// Plain-object status for an item (no BigInts, so it crosses processes as-is).
// installed: on disk and not mid-download/update.
function itemStatus(c, item) {
  const state = Number(c.workshop.state(item)) || 0;
  const info = c.workshop.installInfo(item);
  const dl = c.workshop.downloadInfo(item);
  const has = (flag) => (state & flag) !== 0;
  const busy = has(ITEM_STATE.DOWNLOADING) || has(ITEM_STATE.DOWNLOAD_PENDING);
  return {
    id: item.toString(),
    state,
    subscribed: has(ITEM_STATE.SUBSCRIBED),
    installed: has(ITEM_STATE.INSTALLED) && !busy && !has(ITEM_STATE.NEEDS_UPDATE),
    downloading: busy,
    needsUpdate: has(ITEM_STATE.NEEDS_UPDATE),
    folder: info && info.folder ? String(info.folder) : null,
    bytesDownloaded: dl ? Number(dl.current) : null,
    bytesTotal: dl ? Number(dl.total) : null,
  };
}

// One worker's job handler. loadBinding is injectable for the check harness.
function createWorker({ loadBinding = () => require('steamworks.js'), log = console } = {}) {
  let binding; // undefined: not tried yet; null: failed (bindingError says why)
  let bindingError = null;
  let client = null;

  function getClient() {
    if (binding === undefined) {
      try {
        binding = loadBinding();
      } catch (err) {
        binding = null;
        bindingError = errText(err);
      }
    }
    if (!binding) {
      throw new Error(
        `The Steamworks library (steamworks.js) couldn't be loaded, so Steam Workshop actions are unavailable: ${bindingError}`,
      );
    }
    if (!client) {
      try {
        client = binding.init(APP_ID);
      } catch (err) {
        throw new Error(`Couldn't connect to Steam - is it running and logged in? (${errText(err)})`);
      }
    }
    return client;
  }

  // Calls one SDK function, rewording a failure so it names the action.
  async function sdk(what, fn) {
    try {
      return await fn();
    } catch (err) {
      throw new Error(`Steam ${what} failed: ${errText(err)}`);
    }
  }

  const actions = {
    // Subscribe, then ask Steam to download it right away (high priority). The
    // download itself is async: the caller polls installInfo until installed.
    async subscribe(c, item) {
      await sdk('subscribe', () => c.workshop.subscribe(item));
      try {
        c.workshop.download(item, true); // subscribing queues it anyway; this only bumps priority
      } catch (err) {
        log.warn('[steam worker] download request failed (subscribe still stands):', errText(err));
      }
      return sdk('status check', () => itemStatus(c, item));
    },
    // A resolved unsubscribe isn't proof it took (RimSort has an open bug where
    // it silently doesn't): the caller verifies with isSubscribed.
    async unsubscribe(c, item) {
      await sdk('unsubscribe', () => c.workshop.unsubscribe(item));
      return sdk('status check', () => itemStatus(c, item));
    },
    installInfo: (c, item) => sdk('status check', () => itemStatus(c, item)),
    isSubscribed: async (c, item) => (await sdk('status check', () => itemStatus(c, item))).subscribed,
    // The item's listing as the logged-in client sees it (Scan Issues' title
    // fallback when the keyless Web API says not found). Plain values only:
    // visibility/banned kept so the log line shows why the Web API may differ.
    async workshopItem(c, item) {
      const r = await sdk('workshop item lookup', () => c.workshop.getItem(item));
      return r
        ? { found: true, title: typeof r.title === 'string' ? r.title : null, visibility: r.visibility, banned: !!r.banned }
        : { found: false, title: null };
    },
  };

  // { action, id } -> { ok, value } | { ok: false, error }. Never throws.
  async function handle(msg) {
    try {
      const fn = msg && Object.prototype.hasOwnProperty.call(actions, msg.action) ? actions[msg.action] : null;
      if (!fn) throw new Error(`Unknown Steam helper action: ${msg && msg.action}`);
      const item = toItemId(msg.id);
      return { ok: true, value: await fn(getClient(), item) };
    } catch (err) {
      return { ok: false, error: errText(err) };
    }
  }

  return { handle };
}

// Running as a utility process: serve jobs until told to shut down (or killed).
if (process.parentPort) {
  const worker = createWorker();
  process.parentPort.on('message', async (e) => {
    const msg = (e && e.data) || {};
    if (msg.action === 'shutdown') {
      process.exit(0); // steamworks.js has no shutdown; exiting unregisters us with Steam
      return;
    }
    const res = await worker.handle(msg);
    process.parentPort.postMessage({ seq: msg.seq, ...res });
  });
}

module.exports = { APP_ID, ITEM_STATE, createWorker, itemStatus, toItemId };
