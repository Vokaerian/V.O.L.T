'use strict';
// Window size only (user request 2026-09-26): persisted at
// <base>/window-state.json, not under the per-game APP-ROOT - the window
// exists before any game is chosen. Mirrors settings.js's store shape.
// Position, maximized state and multi-monitor changes aren't handled -
// not asked for.

const path = require('node:path');
const { readJson, writeJson } = require('./fsutil');

const DEFAULTS = Object.freeze({ width: 1600, height: 900 });

function createWindowStateStore(baseRoot) {
  const file = path.join(baseRoot, 'window-state.json');

  async function load() {
    try {
      return { ...DEFAULTS, ...(await readJson(file)) };
    } catch (err) {
      if (err.code !== 'ENOENT') console.warn(`[windowState] ignoring unreadable ${file}: ${err.message}`);
      return { ...DEFAULTS };
    }
  }

  async function save({ width, height }) {
    await writeJson(file, { width, height });
  }

  return { file, load, save };
}

module.exports = { createWindowStateStore, DEFAULTS };
