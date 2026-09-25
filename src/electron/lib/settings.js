'use strict';
// App settings, stored as APP-ROOT/settings.json. Holds the resolved paths
// (autodetected or picked manually), the last-opened load order and the
// user's per-mod colors.

const path = require('node:path');
const { readJson, writeJson } = require('./fsutil');

const DEFAULTS = Object.freeze({
  schemaVersion: 1,
  gameDir: null, // RimWorld install root; Mods folder = <gameDir>/Mods
  gameSource: null, // 'steam' | 'gog' | 'manual'
  configDir: null, // folder holding ModsConfig.xml
  lastLoadOrder: null, // slug
  modColors: {}, // mod id (lowercased packageId) -> '#rrggbb'; global, not per load order
  ignoredScanIssues: [], // scan problem paths hidden from the Scan issues window; global
  // Mod-acquisition mode (SCOPE.md §2a; Settings > Steam; global):
  // 'steamcmd' | 'steamworks' | 'gog', or null = not chosen yet - the renderer
  // then uses 'gog' for a GOG install and 'steamcmd' otherwise (lists.js
  // effectiveAcquireVia). Only setSteamAcquireVia stores a value.
  steamAcquireVia: null,
});

const ACQUIRE_VIA = ['steamcmd', 'steamworks', 'gog'];

function createSettingsStore(appRoot) {
  const file = path.join(appRoot, 'settings.json');
  let cache = null;

  async function get() {
    if (!cache) {
      try {
        cache = { ...DEFAULTS, ...(await readJson(file)) };
      } catch (err) {
        if (err.code !== 'ENOENT') console.warn(`[settings] ignoring unreadable ${file}: ${err.message}`);
        cache = { ...DEFAULTS };
      }
    }
    return { ...cache };
  }

  async function update(patch) {
    cache = { ...(await get()), ...patch };
    await writeJson(file, cache);
    return { ...cache };
  }

  // color: '#rrggbb' to assign, null to clear. Returns the new modColors map.
  async function setModColor(id, color) {
    if (typeof id !== 'string' || !id) throw new Error('setModColor expects a mod id.');
    if (color != null && !/^#[0-9a-f]{6}$/i.test(color)) throw new Error(`Not a #rrggbb color: ${color}`);
    const modColors = { ...(await get()).modColors };
    if (color) modColors[id] = color.toLowerCase();
    else delete modColors[id];
    return (await update({ modColors })).modColors;
  }

  // Adds/removes a scan problem's path from ignoredScanIssues. Returns the new array.
  async function setScanIssueIgnored(p, ignored) {
    if (typeof p !== 'string' || !p) throw new Error('setScanIssueIgnored expects a path.');
    const rest = ((await get()).ignoredScanIssues || []).filter((x) => x !== p);
    return (await update({ ignoredScanIssues: ignored ? [...rest, p] : rest })).ignoredScanIssues;
  }

  // 'steamcmd' | 'steamworks' | 'gog' (an explicit choice: overrides the
  // GOG-install auto-pick). Returns the stored value.
  async function setSteamAcquireVia(via) {
    if (!ACQUIRE_VIA.includes(via)) throw new Error(`Unknown download method: ${via}`);
    return (await update({ steamAcquireVia: via })).steamAcquireVia;
  }

  return { file, get, update, setModColor, setScanIssueIgnored, setSteamAcquireVia };
}

module.exports = { createSettingsStore, DEFAULTS };
