'use strict';
// Windows registry reads via the built-in reg.exe (no native modules).
// Every function resolves to null / [] off Windows or on any failure.

const { execFile } = require('node:child_process');

function regQuery(args) {
  if (process.platform !== 'win32') return Promise.resolve(null);
  return new Promise((resolve) => {
    execFile('reg', ['query', ...args], { windowsHide: true, maxBuffer: 16 * 1024 * 1024 }, (err, stdout) =>
      resolve(err ? null : String(stdout)),
    );
  });
}

// Parses `reg query` output into [{ key, values: { lowercasedName: data } }].
// Value lines look like: "    SteamPath    REG_SZ    c:/program files (x86)/steam"
function parseRegOutput(stdout) {
  const blocks = [];
  let cur = null;
  for (const line of String(stdout || '').split(/\r?\n/)) {
    if (!line.trim()) continue;
    if (/^HKEY_/i.test(line)) {
      cur = { key: line.trim(), values: {} };
      blocks.push(cur);
      continue;
    }
    const m = /^\s+(.*?)\s{4}(REG_[A-Z_]+)(?:\s{4}(.*))?$/.exec(line);
    if (m && cur) cur.values[m[1].toLowerCase()] = (m[3] ?? '').trim();
  }
  return blocks;
}

async function readRegValue(key, name) {
  const out = await regQuery([key, '/v', name]);
  if (!out) return null;
  for (const b of parseRegOutput(out)) {
    const v = b.values[name.toLowerCase()];
    if (v != null && v !== '') return v;
  }
  return null;
}

async function readRegTree(key) {
  const out = await regQuery([key, '/s']);
  return out ? parseRegOutput(out) : [];
}

module.exports = { parseRegOutput, readRegValue, readRegTree };
