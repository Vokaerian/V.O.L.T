'use strict';
// Load orders (SCOPE.md §2a): one folder per load order under
// APP-ROOT/load-orders/<slug>/, holding loadorder.json (the manifest). Mods
// stay in the real Mods folder and are referenced by lowercased packageId.
//
// Manifest (schemaVersion 1):
// {
//   "schemaVersion": 1,
//   "name": "My first load order!",          // display name; folder name is the slug
//   "createdAt": "<ISO>", "updatedAt": "<ISO>",
//   "active":   ["brrainz.harmony", ...],    // ordered = load order
//   "inactive": ["some.mod", ...],           // snapshot of the inactive pane at save time (informational)
//   "pinning": {                             // schema only - copying is NOT implemented yet
//     "enabled": false,                      // keep pinned copies of this load order's mods
//     "useLocalCopies": false,               // toggle: pinned copies (true) vs live installed versions (false)
//     "dir": "pinned",                       // pinned copies live in load-orders/<slug>/<dir>/<mod folder>/
//     "mods": {}                             // packageId -> { folder, sourcePath, copiedAt }
//   }
// }
// Unknown top-level fields are preserved on save (forward compatibility).

const fs = require('node:fs/promises');
const path = require('node:path');
const { slugify, isValidSlug } = require('./slug');
const { readJson, writeJson } = require('./fsutil');
const { cleanIds } = require('./ids');

const DIR_NAME = 'load-orders';
const MANIFEST_FILE = 'loadorder.json';
const SCHEMA_VERSION = 1;

function loadOrdersRoot(appRoot) {
  return path.join(appRoot, DIR_NAME);
}

function defaultPinning() {
  return { enabled: false, useLocalCopies: false, dir: 'pinned', mods: {} };
}

function assertSlug(slug) {
  if (!isValidSlug(slug)) throw new Error(`Invalid load order id: ${JSON.stringify(slug)}`);
}

function manifestPath(appRoot, slug) {
  assertSlug(slug);
  return path.join(loadOrdersRoot(appRoot), slug, MANIFEST_FILE);
}

function normalizeManifest(raw, slug) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('manifest is not a JSON object');
  if (typeof raw.schemaVersion === 'number' && raw.schemaVersion > SCHEMA_VERSION) {
    throw new Error(`manifest schemaVersion ${raw.schemaVersion} is newer than this app supports (${SCHEMA_VERSION})`);
  }
  const pinning = raw.pinning && typeof raw.pinning === 'object' ? raw.pinning : {};
  return {
    slug,
    schemaVersion: SCHEMA_VERSION,
    name: typeof raw.name === 'string' && raw.name.trim() ? raw.name : slug,
    createdAt: raw.createdAt ?? null,
    updatedAt: raw.updatedAt ?? null,
    active: cleanIds(raw.active),
    inactive: cleanIds(raw.inactive),
    pinning: { ...defaultPinning(), ...pinning },
  };
}

async function listLoadOrders(appRoot) {
  let entries;
  try {
    entries = await fs.readdir(loadOrdersRoot(appRoot), { withFileTypes: true });
  } catch (err) {
    if (err.code === 'ENOENT') return [];
    throw err;
  }
  const out = [];
  for (const e of entries) {
    if (!e.isDirectory() || !isValidSlug(e.name)) continue;
    try {
      const m = normalizeManifest(await readJson(manifestPath(appRoot, e.name)), e.name);
      out.push({ slug: e.name, name: m.name, updatedAt: m.updatedAt, activeCount: m.active.length });
    } catch (err) {
      out.push({ slug: e.name, name: e.name, error: err.message });
    }
  }
  const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });
  return out.sort((a, b) => collator.compare(a.name, b.name));
}

// New load order: slug the name, suffix -2, -3... on collision, then write its manifest.
async function createLoadOrder(appRoot, name, lists = {}) {
  const display = String(name ?? '').trim();
  if (!display) throw new Error('Load order name is empty');
  const root = loadOrdersRoot(appRoot);
  await fs.mkdir(root, { recursive: true });
  const base = slugify(display);
  const taken = new Set((await fs.readdir(root)).map((s) => s.toLowerCase()));
  for (let n = 1; n < 1000; n++) {
    const slug = n === 1 ? base : `${base}-${n}`;
    if (taken.has(slug)) continue;
    try {
      await fs.mkdir(path.join(root, slug)); // non-recursive: fails with EEXIST instead of reusing a folder
    } catch (err) {
      if (err.code === 'EEXIST') continue;
      throw err;
    }
    const now = new Date().toISOString();
    const manifest = {
      schemaVersion: SCHEMA_VERSION,
      name: display,
      createdAt: now,
      updatedAt: now,
      active: cleanIds(lists.active),
      inactive: cleanIds(lists.inactive),
      pinning: defaultPinning(),
    };
    await writeJson(manifestPath(appRoot, slug), manifest);
    return normalizeManifest(manifest, slug);
  }
  throw new Error(`Too many load orders named like "${display}"`);
}

async function loadLoadOrder(appRoot, slug) {
  return normalizeManifest(await readJson(manifestPath(appRoot, slug)), slug);
}

// Save: writes the current active/inactive lists to the manifest. No effect on the game.
async function saveLoadOrder(appRoot, slug, lists = {}) {
  const file = manifestPath(appRoot, slug);
  const raw = await readJson(file);
  normalizeManifest(raw, slug); // validates (e.g. refuses a newer schema)
  const next = {
    ...raw,
    schemaVersion: SCHEMA_VERSION,
    active: cleanIds(lists.active),
    inactive: cleanIds(lists.inactive),
    updatedAt: new Date().toISOString(),
  };
  await writeJson(file, next);
  return normalizeManifest(next, slug);
}

module.exports = {
  DIR_NAME,
  MANIFEST_FILE,
  SCHEMA_VERSION,
  loadOrdersRoot,
  listLoadOrders,
  createLoadOrder,
  loadLoadOrder,
  saveLoadOrder,
};
