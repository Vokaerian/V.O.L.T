'use strict';
// RimSort's Community Rules Database: crowd-sourced loadAfter/loadBefore
// rules for mods that don't declare them (well) in their own About.xml.
// https://github.com/RimSort/Community-Rules-Database
//
// A LIVE RUNTIME LOOKUP, not bundled or redistributed with VOLT: the app
// fetches the published file itself, once per process, and keeps the last
// good copy at APP-ROOT/communityRules.json only as an offline fallback.
//
// Sort-rule priority (standing convention, applies to any future rule source
// too): communityRules > About.xml > alphabetical. Alphabetical is always the
// final fallback - a missing/unreachable source just drops out of the merge,
// it never blocks or fails Sort. The merge itself is in the renderer's
// lists.js autoSortActive.

const path = require('node:path');
const { readText, writeFileAtomic } = require('./fsutil');

const RULES_URL = 'https://raw.githubusercontent.com/RimSort/Community-Rules-Database/main/communityRules.json';
const TIMEOUT_MS = 10_000;

// Normalize the file's { rules: { id: { loadAfter: {id: ...}, loadBefore: {id: ...} } } }
// into Map<lowercase id, { loadAfter: string[], loadBefore: string[] }>. Only the
// keys of loadAfter/loadBefore matter; name/comment and any other key (loadTop,
// loadBottom, incompatibleWith, ...) are ignored. Throws if there's no rules object.
function normalizeRules(json) {
  const rules = json && typeof json === 'object' ? json.rules : null;
  if (!rules || typeof rules !== 'object' || Array.isArray(rules)) throw new Error('communityRules.json has no "rules" object');
  const keys = (o) => (o && typeof o === 'object' && !Array.isArray(o) ? Object.keys(o) : []);
  const out = new Map();
  for (const [rawId, entry] of Object.entries(rules)) {
    const id = String(rawId).trim().toLowerCase();
    if (!id || !entry || typeof entry !== 'object') continue;
    const cur = out.get(id) || { loadAfter: [], loadBefore: [] };
    cur.loadAfter.push(...keys(entry.loadAfter));
    cur.loadBefore.push(...keys(entry.loadBefore));
    out.set(id, cur);
  }
  return out;
}

async function fetchLive(cacheFile) {
  const res = await fetch(RULES_URL, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const text = await res.text();
  const rules = normalizeRules(JSON.parse(text)); // validate before overwriting the cache
  try {
    await writeFileAtomic(cacheFile, text);
  } catch (err) {
    console.warn(`[communityRules] could not write cache ${cacheFile}: ${err.message}`);
  }
  return rules;
}

async function load(appRoot) {
  const cacheFile = path.join(appRoot, 'communityRules.json');
  try {
    return { rules: await fetchLive(cacheFile), source: 'live' };
  } catch (err) {
    console.warn(`[communityRules] live fetch failed (${err.message}); trying cached copy`);
  }
  try {
    return { rules: normalizeRules(JSON.parse(await readText(cacheFile))), source: 'cache' };
  } catch (err) {
    if (err.code !== 'ENOENT') console.warn(`[communityRules] cached copy unusable: ${err.message}`);
  }
  return { rules: new Map(), source: 'none' };
}

// Once per process: the first call starts the lookup, every later call (e.g.
// each Sort) shares its result. Never rejects.
let pending = null;
function getCommunityRules(appRoot) {
  if (!pending) pending = load(appRoot).catch(() => ({ rules: new Map(), source: 'none' }));
  return pending;
}

module.exports = { getCommunityRules, normalizeRules, COMMUNITY_RULES_URL: RULES_URL };
