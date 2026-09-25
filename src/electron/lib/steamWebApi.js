'use strict';
// Steam's keyless Web API (PLAN.md item 4): ISteamRemoteStorage endpoints that
// need no personal API key. Distinct from lib/steam.js (the Steamworks *client*
// SDK: subscribe/unsubscribe through the running Steam client) and from
// Workshop search (needs a key; deferred, TODO.md entry 9).
//
// Used by collection import (steam:resolveCollection). Update tracking will
// reuse getPublishedFileDetails (time_updated, subscriber counts), so it
// returns every generally useful field, not just the title.
//
// Plain main-process fetch, like communityRules.js / modListIO.js (and with
// the same known limitation: no system/PAC proxy, TODO.md entry 4). A failed
// request becomes an Error with a readable message; main.js's handle() turns
// that into { ok: false, error }, so nothing here can crash the app.

const API = 'https://api.steampowered.com/ISteamRemoteStorage';
const TIMEOUT_MS = 10_000;
// Ids per GetPublishedFileDetails request. Valve documents no hard cap;
// 100 keeps each request small (PLAN.md item 4: ~100-200).
const DETAILS_CHUNK = 100;
// Collections can list other collections; they're expanded in place, this deep at most.
const MAX_COLLECTION_DEPTH = 3;
const RIMWORLD_APP_ID = 294100;
const RESULT_OK = 1; // Steam EResult k_EResultOK
const FILETYPE_COLLECTION = 2; // EWorkshopFileType k_EWorkshopFileTypeCollection
const WS_ID = /^\d{1,20}$/;

// A pasted collection (or single mod, resolveSingleItem): a bare Workshop id, or a steamcommunity.com
// .../sharedfiles/filedetails/?id=N or .../workshop/filedetails/?id=N page URL
// (scheme optional, extra query params fine). Same normalize-then-check shape
// as modListIO.js rentryPageUrl.
function collectionIdFrom(input) {
  let s = String(input || '').trim();
  if (WS_ID.test(s)) return s;
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(s)) s = 'https://' + s;
  let u;
  try {
    u = new URL(s);
  } catch {
    throw new Error(`Not a Steam Workshop URL or id: ${input}`);
  }
  if (!/^(www\.)?steamcommunity\.com$/i.test(u.hostname)) throw new Error(`Not a steamcommunity.com URL: ${input}`);
  if (!/^\/(sharedfiles|workshop)\/filedetails\/?$/i.test(u.pathname)) {
    throw new Error(`That URL isn't a Steam Workshop page (.../filedetails/?id=...): ${input}`);
  }
  const id = (u.searchParams.get('id') || '').trim();
  if (!WS_ID.test(id)) throw new Error(`That URL has no Workshop id in it: ${input}`);
  return id;
}

function toId(v) {
  const s = String(v ?? '').trim();
  if (!WS_ID.test(s)) throw new Error(`Not a Steam Workshop id: ${v}`);
  return s;
}

const num = (v) => (v === undefined || v === null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

// POST a form-encoded request; returns the reply's `response` object.
async function post(method, fields, appVersion) {
  let res;
  try {
    res = await fetch(`${API}/${method}/v1/`, {
      method: 'POST',
      signal: AbortSignal.timeout(TIMEOUT_MS),
      headers: { 'User-Agent': `VOLT/${appVersion || '?'} Steam Workshop lookup` },
      body: new URLSearchParams(fields),
    });
  } catch (err) {
    throw new Error(`Couldn't reach Steam's Web API (${err && err.message ? err.message : err}). Check your internet connection.`);
  }
  if (!res.ok) throw new Error(`Steam's Web API returned HTTP ${res.status} (${method}).`);
  let j;
  try {
    j = await res.json();
  } catch {
    throw new Error(`Steam's Web API sent a reply VOLT couldn't read (${method}).`);
  }
  if (!j || typeof j.response !== 'object' || !j.response) throw new Error(`Steam's Web API sent an unexpected reply (${method}).`);
  return j.response;
}

// One collection -> { id, children: [{ id, sortOrder, fileType }] } in the
// collection's own order (sortorder). Throws if Steam can't return it (private,
// friends-only, deleted) or it has no children (not a collection, or empty).
async function getCollectionDetails(collectionId, appVersion) {
  const id = toId(collectionId);
  const r = await post('GetCollectionDetails', { collectioncount: '1', 'publishedfileids[0]': id }, appVersion);
  const d = (Array.isArray(r.collectiondetails) ? r.collectiondetails : []).find((x) => x && String(x.publishedfileid) === id);
  if (!d || num(d.result) !== RESULT_OK) {
    throw new Error(`Steam couldn't return collection ${id} (result ${d ? d.result : 'missing'}): it may be private, friends-only or deleted.`);
  }
  const kids = Array.isArray(d.children) ? d.children : [];
  if (!kids.length) throw new Error(`Workshop item ${id} isn't a collection, or the collection is empty.`);
  const children = kids
    .map((c, i) => ({ id: String(c && c.publishedfileid), sortOrder: num(c && c.sortorder) ?? i, fileType: num(c && c.filetype) ?? 0, i }))
    .filter((c) => WS_ID.test(c.id))
    .sort((a, b) => a.sortOrder - b.sortOrder || a.i - b.i)
    .map(({ i, ...c }) => c);
  return { id, children };
}

// Steam's per-item detail record -> a plain object. found=false (only id and
// result set) for an item Steam won't return: removed, private or banned.
function normalizeDetails(id, d) {
  if (!d || num(d.result) !== RESULT_OK) return { id, found: false, result: d ? num(d.result) : null };
  return {
    id,
    found: true,
    result: RESULT_OK,
    title: typeof d.title === 'string' ? d.title : null,
    appId: num(d.consumer_app_id),
    creator: d.creator != null ? String(d.creator) : null,
    fileSize: num(d.file_size),
    previewUrl: typeof d.preview_url === 'string' && d.preview_url ? d.preview_url : null,
    timeCreated: num(d.time_created),
    timeUpdated: num(d.time_updated),
    visibility: num(d.visibility),
    banned: !!num(d.banned),
    subscriptions: num(d.subscriptions),
    lifetimeSubscriptions: num(d.lifetime_subscriptions),
    favorited: num(d.favorited),
    lifetimeFavorited: num(d.lifetime_favorited),
    views: num(d.views),
    tags: Array.isArray(d.tags) ? d.tags.map((t) => (t && typeof t === 'object' ? t.tag : t)).filter((t) => typeof t === 'string') : [],
  };
}

// Workshop ids -> their details, one entry per distinct id, in input order.
// Chunked (DETAILS_CHUNK per request), sequentially.
async function getPublishedFileDetails(ids, appVersion) {
  const list = [...new Set((Array.isArray(ids) ? ids : [ids]).map(toId))];
  const byId = new Map();
  for (let start = 0; start < list.length; start += DETAILS_CHUNK) {
    const chunk = list.slice(start, start + DETAILS_CHUNK);
    const fields = { itemcount: String(chunk.length) };
    chunk.forEach((id, i) => {
      fields[`publishedfileids[${i}]`] = id;
    });
    const r = await post('GetPublishedFileDetails', fields, appVersion);
    for (const d of Array.isArray(r.publishedfiledetails) ? r.publishedfiledetails : []) {
      if (d && d.publishedfileid != null) byId.set(String(d.publishedfileid), d);
    }
  }
  return list.map((id) => normalizeDetails(id, byId.get(id)));
}

// A single Workshop item as a "collection of one" (same shape as
// resolveCollection's reply, plus single: true), or null when Steam doesn't
// return it as an item. A collection page and a single mod's page share one
// URL shape (filedetails/?id=N), so only Steam's reply tells them apart:
// resolveCollection tries this when the collection lookup fails.
// ponytail: an empty collection is told apart from a mod by file_size 0 (mods
// always have a file); use a file_type field if Steam's reply ever needs it.
async function resolveSingleItem(id, appVersion) {
  const [d] = await getPublishedFileDetails([id], appVersion);
  if (!d.found || d.fileSize === 0) return null;
  if (d.appId != null && d.appId !== RIMWORLD_APP_ID) {
    throw new Error(`Workshop item ${id} isn't a RimWorld mod (it belongs to Steam app ${d.appId}).`);
  }
  return {
    collectionId: id,
    single: true,
    title: d.title,
    nestedCollections: 0,
    skippedCollections: 0,
    detailsError: null,
    items: [{ position: 1, id, title: d.title, details: d }],
  };
}

// Collection import: a pasted URL/id -> the collection's items, in order.
// A single mod's URL/id comes back as a one-item collection (resolveSingleItem).
// Nested collections are expanded in place (once each, MAX_COLLECTION_DEPTH
// deep); a duplicate item keeps its first position. Titles come from one
// details lookup; if that fails the ids still come back (title null,
// detailsError set) - names are a nicety, the ordered ids are the import.
// Matching items against installed mods happens in the renderer, which holds
// the scan (lists.js resolveWorkshopPlaceholders).
async function resolveCollection(input, appVersion) {
  const collectionId = collectionIdFrom(input);
  const ids = [];
  const seen = new Set();
  const visited = new Set();
  let nestedCollections = 0;
  let skippedCollections = 0;
  const expand = async (cid, depth) => {
    visited.add(cid);
    const { children } = await getCollectionDetails(cid, appVersion);
    for (const c of children) {
      if (c.fileType === FILETYPE_COLLECTION) {
        if (visited.has(c.id)) continue;
        if (depth >= MAX_COLLECTION_DEPTH) {
          skippedCollections++;
          continue;
        }
        try {
          await expand(c.id, depth + 1);
          nestedCollections++;
        } catch (err) {
          console.warn(`[steamWebApi] nested collection ${c.id} skipped: ${err.message}`);
          skippedCollections++;
        }
      } else if (!seen.has(c.id)) {
        seen.add(c.id);
        ids.push(c.id);
      }
    }
  };
  try {
    await expand(collectionId, 1);
  } catch (err) {
    // Not a (readable, non-empty) collection: maybe a single mod. If that
    // lookup fails too, the collection error is the one reported.
    let single = null;
    try {
      single = await resolveSingleItem(collectionId, appVersion);
    } catch (e) {
      if (/isn't a RimWorld mod/.test(e.message)) throw e;
    }
    if (single) return single;
    throw err;
  }
  if (!ids.length) throw new Error(`Collection ${collectionId} has no Workshop items in it.`);

  let details = null;
  let detailsError = null;
  try {
    details = new Map((await getPublishedFileDetails([collectionId, ...ids], appVersion)).map((d) => [d.id, d]));
  } catch (err) {
    console.warn(`[steamWebApi] item details unavailable: ${err.message}`);
    detailsError = err.message;
  }
  const own = details && details.get(collectionId);
  if (own && own.found && own.appId != null && own.appId !== RIMWORLD_APP_ID) {
    throw new Error(`Collection ${collectionId} isn't a RimWorld collection (it belongs to Steam app ${own.appId}).`);
  }
  return {
    collectionId,
    title: own && own.found ? own.title : null,
    nestedCollections,
    skippedCollections,
    detailsError,
    items: ids.map((id, i) => {
      const d = details ? details.get(id) : null;
      return { position: i + 1, id, title: d && d.found ? d.title : null, details: d || null };
    }),
  };
}

module.exports = {
  collectionIdFrom,
  getCollectionDetails,
  getPublishedFileDetails,
  resolveCollection,
  STEAM_WEB_API: API,
  DETAILS_CHUNK,
};
