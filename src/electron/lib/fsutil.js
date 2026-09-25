'use strict';
// Small filesystem helpers shared by the main-process modules.

const fs = require('node:fs/promises');
const path = require('node:path');

async function exists(p) {
  try {
    await fs.access(p);
    return true;
  } catch {
    return false;
  }
}

async function isDir(p) {
  if (!p) return false;
  try {
    return (await fs.stat(p)).isDirectory();
  } catch {
    return false;
  }
}

function stripBom(text) {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

async function readText(p) {
  return stripBom(await fs.readFile(p, 'utf8'));
}

async function readJson(p) {
  return JSON.parse(await readText(p));
}

// Write via a temp file + rename so a crash mid-write never leaves a
// truncated file behind (matters most for the game's ModsConfig.xml).
async function writeFileAtomic(file, data) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmp, data, 'utf8');
  try {
    await fs.rename(tmp, file);
  } catch (err) {
    await fs.rm(tmp, { force: true }).catch(() => {});
    throw err;
  }
}

async function writeJson(file, obj) {
  await writeFileAtomic(file, JSON.stringify(obj, null, 2) + '\n');
}

// Case-insensitive child lookup: RimWorld mods ship "About/About.xml" in
// assorted casings, which only matters on case-sensitive filesystems.
async function findChildCI(dir, name) {
  let entries;
  try {
    entries = await fs.readdir(dir);
  } catch {
    return null;
  }
  if (entries.includes(name)) return path.join(dir, name);
  const lower = name.toLowerCase();
  const hit = entries.find((e) => e.toLowerCase() === lower);
  return hit ? path.join(dir, hit) : null;
}

// Best-effort recursive delete (Unsubscribe's Workshop-folder cleanup, PLAN.md
// item 4): removes every file and folder it can and skips - never aborts on -
// one it can't (e.g. a file the running game holds open on Windows). A
// read-only file gets one chmod-and-retry. Links are removed, never followed.
// Returns { removed, skipped: [{ path, error }], gone }: files removed, entries
// left behind (a folder is only listed when its own removal failed for a
// reason other than still holding skipped files), and whether `dir` is gone.
async function removeTreeBestEffort(dir) {
  let removed = 0;
  const skipped = [];
  const skip = (p, err) => skipped.push({ path: p, error: (err && (err.code || err.message)) || String(err) });
  const unlinkFile = async (p) => {
    try {
      await fs.unlink(p);
    } catch (err) {
      if (err.code !== 'EPERM' && err.code !== 'EACCES') throw err;
      await fs.chmod(p, 0o666);
      await fs.unlink(p);
    }
  };
  const walk = async (d) => {
    let entries;
    try {
      entries = await fs.readdir(d, { withFileTypes: true });
    } catch (err) {
      if (err.code !== 'ENOENT') skip(d, err);
      return;
    }
    for (const e of entries) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) {
        await walk(p);
        continue;
      }
      try {
        await unlinkFile(p);
        removed++;
      } catch (err) {
        if (err.code !== 'ENOENT') skip(p, err);
      }
    }
    try {
      await fs.rmdir(d);
    } catch (err) {
      if (!['ENOENT', 'ENOTEMPTY', 'EEXIST'].includes(err.code)) skip(d, err);
    }
  };
  await walk(dir);
  return { removed, skipped, gone: !(await exists(dir)) };
}

// Whether `dir` holds nothing but .dds textures (a leftover from an external
// texture-compression tool, not a real mod): true only if the recursive walk
// finds at least one file and every file's extension is .dds (case-insensitive).
// An empty folder is false. excludeAboutFolder skips a top-level "About" folder
// (case-insensitive), for a folder that has About/About.xml but no packageId.
// Links are not followed (they count as a non-.dds entry); an unreadable
// folder counts as "not a leftover".
async function isDdsOnlyLeftover(dir, { excludeAboutFolder = false } = {}) {
  let files = 0;
  const walk = async (d, top) => {
    let entries;
    try {
      entries = await fs.readdir(d, { withFileTypes: true });
    } catch {
      return false;
    }
    for (const e of entries) {
      if (e.isDirectory()) {
        if (top && excludeAboutFolder && e.name.toLowerCase() === 'about') continue;
        if (!(await walk(path.join(d, e.name), false))) return false;
        continue;
      }
      if (!e.isFile() || path.extname(e.name).toLowerCase() !== '.dds') return false;
      files++;
    }
    return true;
  };
  return (await walk(dir, true)) && files > 0;
}

module.exports = { exists, isDir, stripBom, readText, readJson, writeFileAtomic, writeJson, findChildCI, removeTreeBestEffort, isDdsOnlyLeftover };
