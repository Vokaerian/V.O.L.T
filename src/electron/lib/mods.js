'use strict';
// Mod scanning: every sub-folder of a mods root with About/About.xml is a mod.
// Mods are keyed by lowercased packageId (RimWorld treats it case-insensitively
// and ModsConfig.xml stores it lowercased).

const fs = require('node:fs/promises');
const path = require('node:path');
const { parseXml, getCI, text, list, listField } = require('./xml');
const { findChildCI, isDdsOnlyLeftover, isDir, readText } = require('./fsutil');
const { NO_PACKAGE_ID_PREFIX } = require('./ids');
const { readMarkerMode } = require('./steamCmd');

function parseAboutXml(xml) {
  const doc = parseXml(xml);
  const meta = getCI(doc, 'ModMetaData');
  if (!meta || typeof meta !== 'object') throw new Error('no <ModMetaData> root element');
  const authors = [];
  const single = text(getCI(meta, 'author')).trim();
  if (single) authors.push(single);
  for (const a of list(getCI(meta, 'authors'))) if (!authors.includes(a)) authors.push(a);
  return {
    name: text(getCI(meta, 'name')).trim(),
    packageId: text(getCI(meta, 'packageId')).trim(),
    authors,
    description: text(getCI(meta, 'description')).trim(),
    supportedVersions: list(getCI(meta, 'supportedVersions')),
    // Raw packageIds as written (not lowercased); compare case-insensitively.
    loadAfter: list(getCI(meta, 'loadAfter')),
    loadBefore: list(getCI(meta, 'loadBefore')),
    // Hard dependencies: the packageId of each <li> (download info ignored).
    modDependencies: listField(getCI(meta, 'modDependencies'), 'packageId'),
    // Plain <li>packageId</li> strings, like loadAfter (not structured like modDependencies).
    incompatibleWith: list(getCI(meta, 'incompatibleWith')),
  };
}

function makeMod(about, modDir, folder, source) {
  const warnings = [];
  let id = about.packageId.toLowerCase();
  if (!id) {
    id = NO_PACKAGE_ID_PREFIX + folder.toLowerCase();
    warnings.push('About.xml has no packageId - this mod cannot be written to ModsConfig.xml.');
  }
  return {
    id,
    packageId: about.packageId,
    name: about.name || folder,
    authors: about.authors,
    description: about.description,
    supportedVersions: about.supportedVersions,
    loadAfter: about.loadAfter,
    loadBefore: about.loadBefore,
    modDependencies: about.modDependencies,
    incompatibleWith: about.incompatibleWith,
    path: modDir,
    folder,
    source,
    warnings,
  };
}

async function scanDir(dir, rootSource) {
  let entries;
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch (err) {
    if (err.code === 'ENOENT') return [{ problem: { kind: 'missing-folder', path: dir, message: 'Folder does not exist' } }];
    throw new Error(`Can't read mods folder ${dir}: ${err.message}`);
  }
  return Promise.all(
    entries.map(async (e) => {
      if (!(e.isDirectory() || e.isSymbolicLink())) return null;
      const modDir = path.join(dir, e.name);
      if (!(await isDir(modDir))) return null; // dangling link
      // A Mods folder VOLT copied in from a SteamCMD download (lib/steamCmd.js
      // MARKER) isn't a hand-installed 'local' mod: its marker's mode decides
      // (steamCmd.js readMarkerMode) - 'steamcmd' (temporary, Sync to Steam
      // replaces it) or 'gog' (permanent). An older marker with no mode field
      // reads as 'steamcmd'. Only honoured under Mods ('local' root).
      const source = (rootSource === 'local' && (await readMarkerMode(modDir))) || rootSource;
      const aboutDir = await findChildCI(modDir, 'About');
      const aboutFile = aboutDir && (await findChildCI(aboutDir, 'About.xml'));
      if (!aboutFile) {
        // Narrow carve-out: a folder of nothing but .dds textures (texture-
        // compression leftover) is listed as a tagged no-packageId mod instead
        // of a generic no-about scan issue. Anything else keeps the no-about problem.
        if (await isDdsOnlyLeftover(modDir, { excludeAboutFolder: false })) {
          const about = { name: '', packageId: '', authors: [], description: '', supportedVersions: [], loadAfter: [], loadBefore: [], modDependencies: [], incompatibleWith: [] };
          return { mod: { ...makeMod(about, modDir, e.name, source), ddsLeftover: true } };
        }
        return { problem: { kind: 'no-about', path: modDir, message: 'No About/About.xml - not a mod folder' } };
      }
      try {
        const about = parseAboutXml(await readText(aboutFile));
        const mod = makeMod(about, modDir, e.name, source);
        // Only the no-packageId case is checked (never a normal mod): About/ is
        // skipped since About.xml itself is never a .dds.
        if (!about.packageId && (await isDdsOnlyLeftover(modDir, { excludeAboutFolder: true }))) mod.ddsLeftover = true;
        return { mod };
      } catch (err) {
        return { problem: { kind: 'parse-error', path: modDir, message: `About.xml could not be parsed: ${err.message}` } };
      }
    }),
  );
}

// roots: [{ dir, source }]. Earlier roots win on duplicate package ids.
// The key a mod name sorts by: leading "[TAG]" groups (plus the whitespace
// after each) stripped, so "[NL] Custom Portraits" and "[1.6][FSF] Name" sort
// under C / N. Only a *leading* bracket counts; if nothing is left after
// stripping, the original name is the key. Sort key only - the displayed name
// is never changed.
// KEEP IN SYNC: identical copy in src/renderer/src/lists.js (sortIdsByName:
// Inactive order + Sort's alphabetical fallback); main and renderer are
// separate bundles, so the logic is duplicated like the collator below.
function sortKeyName(name) {
  const s = String(name ?? '');
  return s.replace(/^(?:\[[^\]]*\]\s*)+/, '') || s;
}

// One side of a duplicate-id problem, structured for the Scan Issues window
// (which looks up Workshop listing titles when both names are identical).
// workshopId: same rule as the renderer's lists.js workshopId() - KEEP IN SYNC.
function dupSide(m) {
  const wid = ['workshop', 'steamcmd', 'gog'].includes(m.source) && /^\d+$/.test(m.folder) ? m.folder : null;
  return { name: m.name, path: m.path, workshopId: wid };
}

async function scanModRoots(roots) {
  const mods = [];
  const problems = [];
  const byId = new Map();
  for (const { dir, source } of roots) {
    for (const r of await scanDir(dir, source)) {
      if (!r) continue;
      if (r.problem) {
        problems.push(r.problem);
        continue;
      }
      const m = r.mod;
      const prev = byId.get(m.id);
      if (prev) {
        prev.warnings.push(`Another copy with the same package ID is at ${m.path} (ignored).`);
        problems.push({
          kind: 'duplicate-id',
          path: m.path,
          message: `Duplicate package ID "${m.packageId}"\n\nKept: ${prev.name}\n${prev.path}\n\nIgnored: ${m.name}\n${m.path}`,
          kept: dupSide(prev),
          ignored: dupSide(m),
        });
        continue;
      }
      byId.set(m.id, m);
      mods.push(m);
    }
  }
  const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });
  mods.sort((a, b) => collator.compare(sortKeyName(a.name), sortKeyName(b.name)));
  return { mods, problems };
}

// <modDir>/About/Preview.png (case-insensitive) as a data URL, or null.
async function readPreviewDataUrl(modDir) {
  const aboutDir = await findChildCI(modDir, 'About');
  const file = aboutDir && (await findChildCI(aboutDir, 'Preview.png'));
  if (!file) return null;
  try {
    return `data:image/png;base64,${(await fs.readFile(file)).toString('base64')}`;
  } catch {
    return null;
  }
}

module.exports = { parseAboutXml, scanModRoots, readPreviewDataUrl, sortKeyName };
