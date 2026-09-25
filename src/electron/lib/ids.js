'use strict';
// Mod id helpers shared by scanning, ModsConfig.xml and load-order manifests.
// A mod id is its lowercased packageId.

// Fallback id for a mod whose About.xml has no packageId. Never pushed to ModsConfig.xml.
const NO_PACKAGE_ID_PREFIX = 'folder:';
// Pending Workshop placeholder (collection/rentry import of an item that isn't
// installed yet). May be saved in a load order; never pushed or exported.
const PENDING_WORKSHOP_PREFIX = 'workshop:';

// Whether an id may be written to a ModsConfig.xml (Push, RimPy .xml export).
function isWritableId(id) {
  return !id.startsWith(NO_PACKAGE_ID_PREFIX) && !id.startsWith(PENDING_WORKSHOP_PREFIX);
}

// Trim, lowercase, drop non-strings/empties/duplicates, keep order.
function cleanIds(ids) {
  const seen = new Set();
  const out = [];
  for (const raw of Array.isArray(ids) ? ids : []) {
    if (typeof raw !== 'string') continue;
    const id = raw.trim().toLowerCase();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

module.exports = { NO_PACKAGE_ID_PREFIX, PENDING_WORKSHOP_PREFIX, isWritableId, cleanIds };
