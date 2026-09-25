'use strict';
// The game's real ModsConfig.xml. Reading is harmless; writing happens ONLY via
// pushModsConfig (the "Push" action, SCOPE.md §2a). Push replaces just the
// <activeMods> block and leaves everything else in the file byte-for-byte
// (version, knownExpansions, BOM, line endings), after copying the current
// file to ModsConfig.xml.volt-backup.

const fs = require('node:fs/promises');
const path = require('node:path');
const { parseXml, getCI, text, list, escapeXml } = require('./xml');
const { exists, isDir, writeFileAtomic } = require('./fsutil');
const { isWritableId, cleanIds } = require('./ids');

const FILE_NAME = 'ModsConfig.xml';
const BACKUP_SUFFIX = '.volt-backup';

function modsConfigPath(configDir) {
  return path.join(configDir, FILE_NAME);
}

async function readModsConfig(configDir) {
  const file = modsConfigPath(configDir);
  if (!(await exists(file))) return { path: file, exists: false, version: null, activeMods: [], knownExpansions: [] };
  const root = getCI(parseXml(await fs.readFile(file, 'utf8')), 'ModsConfigData') || {};
  return {
    path: file,
    exists: true,
    version: text(getCI(root, 'version')).trim() || null,
    activeMods: cleanIds(list(getCI(root, 'activeMods'))),
    knownExpansions: list(getCI(root, 'knownExpansions')),
  };
}

function renderActiveMods(ids, indent, eol) {
  if (!ids.length) return '<activeMods />';
  const child = indent + (indent.length ? indent : '  ');
  return ['<activeMods>', ...ids.map((id) => `${child}<li>${escapeXml(id)}</li>`), `${indent}</activeMods>`].join(eol);
}

// Returns xmlText with its <activeMods> block replaced by `ids`.
function applyActiveMods(xmlText, ids) {
  const eol = xmlText.includes('\r\n') ? '\r\n' : '\n';
  const block = /^([ \t]*)(<activeMods\b[^>]*\/>|<activeMods\b[^>]*>[\s\S]*?<\/activeMods\s*>)/m;
  const m = block.exec(xmlText);
  if (m) {
    return xmlText.slice(0, m.index) + m[1] + renderActiveMods(ids, m[1], eol) + xmlText.slice(m.index + m[0].length);
  }
  const close = /^([ \t]*)<\/ModsConfigData\s*>/m.exec(xmlText);
  if (!close) throw new Error("ModsConfig.xml doesn't look like a RimWorld mods config (no <ModsConfigData>); refusing to overwrite it");
  const indent = '  ';
  return xmlText.slice(0, close.index) + indent + renderActiveMods(ids, indent, eol) + eol + xmlText.slice(close.index);
}

function freshModsConfig(ids, gameVersion, eol) {
  const lines = ['<?xml version="1.0" encoding="utf-8"?>', '<ModsConfigData>'];
  if (gameVersion) lines.push(`  <version>${escapeXml(gameVersion)}</version>`);
  lines.push('  ' + renderActiveMods(ids, '  ', eol), '</ModsConfigData>', '');
  return lines.join(eol);
}

async function pushModsConfig(configDir, activeIds, { gameVersion = null } = {}) {
  if (!(await isDir(configDir))) {
    throw new Error(`Config folder not found: ${configDir}. Launch RimWorld once, or set the folder manually.`);
  }
  const all = cleanIds(activeIds);
  const ids = all.filter(isWritableId);
  const file = modsConfigPath(configDir);
  let out;
  let backupPath = null;
  if (await exists(file)) {
    const current = await fs.readFile(file, 'utf8');
    out = applyActiveMods(current, ids);
    backupPath = file + BACKUP_SUFFIX;
    await fs.copyFile(file, backupPath);
  } else {
    out = freshModsConfig(ids, gameVersion, process.platform === 'win32' ? '\r\n' : '\n');
  }
  await writeFileAtomic(file, out);
  return { path: file, backupPath, count: ids.length, skipped: all.length - ids.length };
}

module.exports = { modsConfigPath, readModsConfig, applyActiveMods, freshModsConfig, pushModsConfig };
