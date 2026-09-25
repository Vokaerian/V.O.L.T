// Pure helpers for the inactive/active mod lists. Lists are arrays of mod ids
// (lowercased packageIds); `mods` is a Map id -> scanned mod.

const collator = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });

export function modName(mods, id) {
  const m = mods.get(id);
  return m ? m.name : id;
}

// Same ids, in the same order (used for dirty-tracking and undo no-op checks).
export function sameIds(a, b) {
  return a.length === b.length && a.every((id, i) => id === b[i]);
}

// The key a mod name sorts by: leading "[TAG]" groups (plus the whitespace
// after each) stripped, so "[NL] Custom Portraits" and "[1.6][FSF] Name" sort
// under C / N. Only a *leading* bracket counts; if nothing is left after
// stripping, the original name is the key. Sort key only - the displayed name
// is never changed.
// KEEP IN SYNC: identical copy in src/electron/lib/mods.js (scan-time sort);
// main and renderer are separate bundles, so the logic is duplicated like the
// collator above.
export function sortKeyName(name) {
  const s = String(name ?? '');
  return s.replace(/^(?:\[[^\]]*\]\s*)+/, '') || s;
}

export function sortIdsByName(ids, mods) {
  return [...ids].sort((a, b) => collator.compare(sortKeyName(modName(mods, a)), sortKeyName(modName(mods, b))));
}

// Active keeps every given id in order (ids not found on disk stay, shown as
// "not found" placeholders, so Save/Push never silently drop them). A pending
// "workshop:<id>" placeholder whose Workshop item is now scanned (Subscribed,
// then Rescan) is swapped in place for that mod's packageId; if the mod was
// already active the first occurrence wins, as for any duplicate. Inactive
// is recomputed: every scanned mod that isn't active, sorted by name.
export function reconcileLists(mods, activeIds) {
  const byWid = new Map();
  for (const m of mods.values()) {
    const wid = workshopId(m);
    if (wid) byWid.set(wid, m.id);
  }
  const seen = new Set();
  const active = [];
  for (const raw of activeIds || []) {
    let id = String(raw).trim().toLowerCase();
    if (id.startsWith('workshop:') && byWid.has(id.slice(9))) id = byWid.get(id.slice(9));
    if (!id || seen.has(id)) continue;
    seen.add(id);
    active.push(id);
  }
  const inactive = [];
  for (const id of mods.keys()) if (!seen.has(id)) inactive.push(id);
  return { active, inactive: sortIdsByName(inactive, mods) };
}

// Core first, then the DLCs in release order; any other official content after, by name.
const OFFICIAL_ORDER = [
  'ludeon.rimworld',
  'ludeon.rimworld.royalty',
  'ludeon.rimworld.ideology',
  'ludeon.rimworld.biotech',
  'ludeon.rimworld.anomaly',
  'ludeon.rimworld.odyssey',
];

// Official ids (Core/DLC) in load order: OFFICIAL_ORDER first, any unknown
// official id after them, name-sorted.
function sortOfficialIds(ids, mods) {
  const rank = (id) => {
    const i = OFFICIAL_ORDER.indexOf(id);
    return i < 0 ? OFFICIAL_ORDER.length : i;
  };
  return sortIdsByName(ids, mods).sort((a, b) => rank(a) - rank(b)); // stable: unknown official ids stay name-sorted
}

// Every scanned official id (Core + DLC, from <game>/Data), in load order.
// Shared by blankLists and collection import (App.jsx onCollectionImport: a
// Workshop collection can only hold Workshop items, never Core/DLC).
export function officialIds(mods) {
  return sortOfficialIds(
    [...mods.values()].filter((m) => m.source === 'official').map((m) => m.id),
    mods,
  );
}

// Status-text name for a set of official ids: "Core", "Core and 2 DLC",
// "1 DLC" (any non-Core official content counts as DLC).
export function officialPhrase(ids) {
  const core = ids.includes(OFFICIAL_ORDER[0]);
  const dlc = ids.length - (core ? 1 : 0);
  return [core && 'Core', dlc && `${dlc} DLC`].filter(Boolean).join(' and ');
}

// A blank load order: only Core + DLC (scanned from <game>/Data) active.
export function blankLists(mods) {
  return reconcileLists(mods, officialIds(mods));
}

// Every load-order rule among the active ids, from all three rule sources
// (communityRules > About.xml > dependency), as a flat list:
// { rules: [{ before, after, declaredBy, source }], overridden, dependencyConflicts }.
// - before/after: ids, "before must load before after". declaredBy: the mod
//   whose own rule (its community-rules entry, its About.xml loadBefore/
//   loadAfter, or its About.xml modDependencies) produced it - always one of
//   before/after. source: 'community' | 'about' | 'dependency'.
// - Only rules where both ids are in `active` count (packageIds compared
//   case-insensitively); self-rules are ignored. A repeated active id's rules
//   are read once. Explicit duplicates (e.g. A.loadBefore B plus B.loadAfter
//   A) are all listed, each with its own declaredBy; consumers dedupe as they
//   need.
// - An About.xml rule that is the exact opposite of a community rule for the
//   same pair is dropped (override-not-merge) and counted in `overridden`.
// - Dependency rules (lowest priority): each active, scanned mod's
//   modDependencies entry naming another active, scanned mod D implies
//   "D before the mod" (declaredBy: the dependent). It only fills gaps the
//   explicit rules (community + surviving About.xml) leave: when an explicit
//   rule already orders the pair the same way, the dependency rule is
//   redundant and not listed (so one misplaced pair is one rule, reported
//   under the explicit rule's kind); when one orders it the opposite way, the
//   dependency rule is dropped (override-not-merge) and recorded in
//   `dependencyConflicts`. A dependency named twice by the same mod counts
//   once.
// - dependencyConflicts: [{ dependent, dependency, sources }], one entry per
//   dropped (dependent, dependency) pair: `dependent` needs `dependency`, but
//   an explicit rule says dependent loads before dependency. sources: the
//   source(s) of those conflicting explicit rules, 'community' before
//   'about', no repeats.
// Single source of truth for autoSortActive (edges) and validateActive (order
// violations): a new rule source only needs adding here.
export function buildOrderConstraints(active, mods, communityRules) {
  const on = new Set(active || []);
  const lookup = (pid) => {
    const id = String(pid).trim().toLowerCase();
    return on.has(id) ? id : undefined;
  };
  const rules = [];
  const add = (before, after, declaredBy, source) => {
    if (before === undefined || after === undefined || before === after) return;
    rules.push({ before, after, declaredBy, source });
  };
  // Community rules first; remember each rule's direction ("a>b": a before b).
  const communityEdges = new Set();
  for (const id of on) {
    const c = communityRules && communityRules.get(id);
    if (!c) continue;
    for (const pid of c.loadBefore || []) add(id, lookup(pid), id, 'community');
    for (const pid of c.loadAfter || []) add(lookup(pid), id, id, 'community');
  }
  for (const r of rules) communityEdges.add(`${r.before}>${r.after}`);
  // Then About.xml. A community rule wins outright over a conflicting
  // About.xml rule for the same pair (communityRules > About.xml >
  // dependency > alphabetical - SCOPE.md §4a): the About.xml rule is
  // dropped, not merged. Revisit if override-not-merge proves too blunt
  // (TODO.md).
  let overridden = 0;
  const addAbout = (before, after, declaredBy) => {
    if (before !== undefined && after !== undefined && communityEdges.has(`${after}>${before}`)) {
      overridden++;
      return;
    }
    add(before, after, declaredBy, 'about');
  };
  for (const id of on) {
    const m = mods.get(id);
    if (!m) continue;
    for (const pid of m.loadBefore || []) addAbout(id, lookup(pid), id);
    for (const pid of m.loadAfter || []) addAbout(lookup(pid), id, id);
  }
  // Every surviving explicit edge (community + About.xml) -> its source(s),
  // in priority order.
  const explicitEdges = new Map();
  for (const r of rules) {
    const key = `${r.before}>${r.after}`;
    const sources = explicitEdges.get(key);
    if (!sources) explicitEdges.set(key, [r.source]);
    else if (!sources.includes(r.source)) sources.push(r.source);
  }
  // Finally modDependencies: dependency before dependent, where no explicit
  // rule already orders the pair.
  const dependencyConflicts = [];
  for (const id of on) {
    const m = mods.get(id);
    if (!m) continue;
    const seen = new Set();
    for (const pid of m.modDependencies || []) {
      const dep = lookup(pid);
      if (dep === undefined || dep === id || !mods.has(dep) || seen.has(dep)) continue;
      seen.add(dep);
      if (explicitEdges.has(`${dep}>${id}`)) continue; // already ordered this way
      const against = explicitEdges.get(`${id}>${dep}`);
      if (against) dependencyConflicts.push({ dependent: id, dependency: dep, sources: [...against] });
      else add(dep, id, id, 'dependency');
    }
  }
  return { rules, overridden, dependencyConflicts };
}

// One-click "Sort" (PLAN.md 2a): reorder the active list by RimSort's
// community rules, each mod's own About.xml loadAfter/loadBefore, and its
// About.xml modDependencies (a dependency loads before the mod needing it).
// Returns { active, unresolved, overridden, dependencyConflicts }: the same
// ids (none added, dropped or duplicated), the number of ordering constraints
// that had to be dropped to break cycles, the number of About.xml rules
// dropped because a community rule says the opposite, and the number of
// (dependent, dependency) pairs whose dependency ordering was dropped because
// a community or About.xml rule says the opposite (buildOrderConstraints).
//
// - Rule sources, highest priority first (standing convention, applies to any
//   future rule source too): communityRules > About.xml > dependency >
//   alphabetical. Alphabetical (the base rank below) is always the final
//   fallback.
//   `communityRules` is a Map lowercase id -> { loadAfter: string[],
//   loadBefore: string[] } (electron/lib/communityRules.js; empty Map if not
//   given or not fetched). Its rules are read exactly like About.xml's, for
//   every active mod it has an entry for. When an About.xml rule would add the
//   exact opposite of a community edge for the same pair of mods, the
//   About.xml rule is skipped (not negotiated) and counted in `overridden`;
//   agreeing rules just count once. Dependency rules only apply to pairs no
//   community/About.xml rule orders (see buildOrderConstraints).
// - One topological sort over every active id. A constraint "A before B"
//   exists when A.loadBefore names B or B.loadAfter names A (or, lowest
//   priority, B's modDependencies names A) (packageIds compared
//   case-insensitively), whatever A and B are, official included.
//   Rules naming a mod that isn't in the active list are ignored. Duplicate
//   rules count once.
// - Official mods (Core/DLC) keep their relative order through a synthetic
//   chain: each one in blankLists' order (Core, DLCs by release, unknown
//   official ids by name) must load after the previous one. A real rule can
//   still put another mod before or between them (e.g. a mod whose
//   loadBefore names Core).
// - Base rank: official mods first in that order, then every other id by
//   name. A mod's effective rank is the lowest base rank of anything it must
//   load before (itself included), so a mod that has to precede Core is
//   pulled up to just before Core instead of dragging every alphabetically
//   earlier mod ahead of Core with it.
// - Kahn's algorithm, always emitting the ready mod (no unplaced predecessor)
//   with the lowest (effective rank, base rank). With no rules at all the
//   result is Core, DLCs in release order, then everything else by name.
// - Cycle (nothing ready): follow unplaced predecessors from the lowest-ranked
//   unplaced mod, always taking the lowest-ranked predecessor, until a mod
//   repeats; the mods between the repeats form a cycle. Its lowest-ranked
//   member is placed anyway, and every rule from a still-unplaced mod into it
//   is dropped and counted in `unresolved`. Mods merely waiting behind a
//   cycle keep their rules.
export function autoSortActive(active, mods, communityRules = new Map()) {
  const ids = [...(active || [])];
  const isOfficial = (id) => mods.get(id)?.source === 'official';
  // Base-rank order: index in `ranked` is the base rank.
  const ranked = [...sortOfficialIds(ids.filter(isOfficial), mods), ...sortIdsByName(ids.filter((id) => !isOfficial(id)), mods)];

  const n = ranked.length;
  const indexOf = new Map(); // id -> first position in ranked
  ranked.forEach((id, i) => {
    if (!indexOf.has(id)) indexOf.set(id, i);
  });
  const succ = Array.from({ length: n }, () => new Set());
  const pred = Array.from({ length: n }, () => new Set());
  const addEdge = (a, b) => {
    if (a === undefined || b === undefined || a === b || succ[a].has(b)) return;
    succ[a].add(b);
    pred[b].add(a);
  };
  // Synthetic chain keeping official mods in their own order.
  let prevOfficial;
  ranked.forEach((id, i) => {
    if (indexOf.get(id) !== i || !isOfficial(id)) return;
    if (prevOfficial !== undefined) addEdge(prevOfficial, i);
    prevOfficial = i;
  });
  // Rules (community + About.xml + dependency), shared with validateActive's
  // order-violation check so the two never drift apart.
  const { rules, overridden, dependencyConflicts } = buildOrderConstraints(ids, mods, communityRules);
  for (const r of rules) addEdge(indexOf.get(r.before), indexOf.get(r.after));

  // Effective rank: lowest base rank reachable along successors. Walking
  // predecessors from each rank in ascending order assigns every mod once.
  const eff = new Array(n).fill(-1);
  for (let r = 0; r < n; r++) {
    if (eff[r] >= 0) continue;
    eff[r] = r;
    const stack = [r];
    while (stack.length) {
      for (const p of pred[stack.pop()]) {
        if (eff[p] < 0) {
          eff[p] = r;
          stack.push(p);
        }
      }
    }
  }
  const before = (a, b) => eff[a] < eff[b] || (eff[a] === eff[b] && a < b);

  const placed = new Array(n).fill(false);
  const waiting = pred.map((p) => p.size); // unplaced predecessors per mod
  const out = [];
  let unresolved = 0;
  const place = (i) => {
    placed[i] = true;
    out.push(ranked[i]);
    for (const s of succ[i]) if (!placed[s]) waiting[s]--;
  };
  const lowestUnplaced = (candidates) => {
    let best = -1;
    for (const i of candidates) if (!placed[i] && (best < 0 || before(i, best))) best = i;
    return best;
  };
  const all = [...Array(n).keys()];

  while (out.length < n) {
    let next = -1;
    for (let i = 0; i < n; i++) {
      if (!placed[i] && waiting[i] === 0 && (next < 0 || before(i, next))) next = i;
    }
    if (next < 0) {
      // Every unplaced mod waits on another unplaced one: find a cycle.
      let cur = lowestUnplaced(all);
      const step = new Map();
      const path = [];
      while (!step.has(cur)) {
        step.set(cur, path.length);
        path.push(cur);
        cur = lowestUnplaced(pred[cur]);
      }
      next = lowestUnplaced(path.slice(step.get(cur)));
      unresolved += waiting[next];
      waiting[next] = 0;
    }
    place(next);
  }

  return { active: out, unresolved, overridden, dependencyConflicts: dependencyConflicts.length };
}

// RimWorld "major.minor" of a version string ("1.6.4871 rev590" -> [1, 6]), or null.
function majorMinor(v) {
  const m = /^(\d+)\.(\d+)/.exec(String(v == null ? '' : v).trim());
  return m ? [Number(m[1]), Number(m[2])] : null;
}

// Outdated: the mod declares supportedVersions and the highest of them
// (major.minor only) is below the installed game's major.minor. False
// whenever either side is unknown or unparseable - never marked on doubt.
export function isOutdated(mod, gameVersion) {
  const game = majorMinor(gameVersion);
  if (!game || !mod || !Array.isArray(mod.supportedVersions)) return false;
  let max = null;
  for (const v of mod.supportedVersions) {
    const mm = majorMinor(v);
    if (mm && (!max || mm[0] > max[0] || (mm[0] === max[0] && mm[1] > max[1]))) max = mm;
  }
  if (!max) return false;
  return max[0] < game[0] || (max[0] === game[0] && max[1] < game[1]);
}

// Hard-dependency index from About.xml modDependencies, over every scanned
// mod: { dependsOn: Map<id, Set<id>>, dependedOnBy: Map<id, Set<id>> }. Ids
// are lowercased packageIds; a dependency naming an unscanned mod (or the mod
// itself) is left out. Pure function of `mods`, so callers can memoize it.
export function buildDependencyIndex(mods) {
  const dependsOn = new Map();
  const dependedOnBy = new Map();
  const add = (map, key, val) => {
    let set = map.get(key);
    if (!set) map.set(key, (set = new Set()));
    set.add(val);
  };
  for (const m of mods.values()) {
    for (const pid of m.modDependencies || []) {
      const dep = String(pid).trim().toLowerCase();
      if (!dep || dep === m.id || !mods.has(dep)) continue;
      add(dependsOn, m.id, dep);
      add(dependedOnBy, dep, m.id);
    }
  }
  return { dependsOn, dependedOnBy };
}

// Live load-order validation (Phase 2b, warn-only). Pure function of the
// active list, the scanned mods and the community rules; cheap enough to
// recompute on every change. Returns:
// - issues: one entry per (active mod, kind), grouped by mod in active order,
//   warnings before errors within a mod:
//   { key, modId, kind, severity, targets: [id] }, kind is
//     'order-before'     - (warning) this mod's own loadBefore rule (About.xml
//                          or its community-rules entry) names these active
//                          mods, but it currently loads after them.
//     'order-after'      - (warning) same, for its own loadAfter rules: it
//                          currently loads before these.
//     'order-dependency' - (warning) modDependencies that are active but
//                          currently load after this mod (the 'dependency'
//                          rules from buildOrderConstraints; a pair an
//                          explicit rule already orders the same way is
//                          reported under that rule's kind instead, so one
//                          misplaced pair is one warning). Sort fixes these.
//     'order-dependency-conflict' - (warning) modDependencies that are active
//                          and currently load after this mod, where Sort
//                          won't move them: a community or About.xml rule
//                          says this mod loads before them
//                          (buildOrderConstraints' dependencyConflicts). The
//                          issue also carries `ruleSources`: the conflicting
//                          rules' sources over all its targets ('community'
//                          before 'about', no repeats). With the dependency
//                          loaded before this mod instead, the explicit rule
//                          is the one violated ('order-before'/'order-after').
//     'inactive'         - (error) modDependencies scanned but not active
//     'not-found'        - (error) modDependencies no scanned mod provides
//     'conflict'         - (error) incompatibleWith pairs where both mods are
//                          active; symmetric, so both mods of a pair get an
//                          entry whichever side declared it.
//   Order kinds use the same rules Sort does (buildOrderConstraints), are
//   attributed to the mod that declared the rule (both mods when both
//   declare one), and only compare mods that are active and found on disk.
//   Their targets are in active-list order.
// - conflicts: Map<id, Set<id>> of those active conflict pairs, both ways.
// Ids are lowercased packageIds; active ids not found on disk are skipped.
export function validateActive(active, mods, communityRules = new Map()) {
  const on = new Set(active);
  const norm = (pid) => String(pid).trim().toLowerCase();
  const pos = new Map(); // id -> first position in the active list
  (active || []).forEach((id, i) => {
    if (!pos.has(id)) pos.set(id, i);
  });
  const conflicts = new Map();
  const addTo = (map, a, b) => {
    let set = map.get(a);
    if (!set) map.set(a, (set = new Set()));
    set.add(b);
  };
  for (const id of on) {
    const m = mods.get(id);
    for (const pid of (m && m.incompatibleWith) || []) {
      const other = norm(pid);
      if (!other || other === id || !on.has(other)) continue;
      addTo(conflicts, id, other);
      addTo(conflicts, other, id);
    }
  }
  // Order violations, keyed by the declaring mod (for a dependency rule: the dependent).
  const shouldBefore = new Map(); // declarer -> ids it should load before
  const shouldAfter = new Map(); // declarer -> ids it should load after
  const depLater = new Map(); // dependent -> active dependencies loading after it
  const constraints = buildOrderConstraints(active, mods, communityRules);
  for (const r of constraints.rules) {
    if (!mods.has(r.before) || !mods.has(r.after) || pos.get(r.before) < pos.get(r.after)) continue;
    if (r.source === 'dependency') addTo(depLater, r.after, r.before);
    else if (r.declaredBy === r.before) addTo(shouldBefore, r.before, r.after);
    else addTo(shouldAfter, r.after, r.before);
  }
  // Dependency orderings Sort won't apply (a conflicting explicit rule), where
  // the dependency currently loads after its dependent.
  const depBlocked = new Map(); // dependent -> such dependencies
  const blockedBy = new Map(); // dependent -> Set of conflicting rule sources
  for (const c of constraints.dependencyConflicts) {
    if (pos.get(c.dependency) < pos.get(c.dependent)) continue;
    addTo(depBlocked, c.dependent, c.dependency);
    for (const src of c.sources) addTo(blockedBy, c.dependent, src);
  }
  const byPos = (set) => [...(set || [])].sort((a, b) => pos.get(a) - pos.get(b));
  const issues = [];
  const push = (modId, kind, severity, targets, extra) => {
    if (targets.length) issues.push({ key: `${modId}|${kind}`, modId, kind, severity, targets, ...extra });
  };
  const sourceOrder = ['community', 'about'];
  for (const id of on) {
    const m = mods.get(id);
    if (!m) continue;
    const inactive = new Set();
    const notFound = new Set();
    for (const pid of m.modDependencies || []) {
      const dep = norm(pid);
      if (!dep || dep === id || on.has(dep)) continue; // active ones: order rules above
      (mods.has(dep) ? inactive : notFound).add(dep);
    }
    push(id, 'order-before', 'warning', byPos(shouldBefore.get(id)));
    push(id, 'order-after', 'warning', byPos(shouldAfter.get(id)));
    push(id, 'order-dependency', 'warning', byPos(depLater.get(id)));
    push(id, 'order-dependency-conflict', 'warning', byPos(depBlocked.get(id)), {
      ruleSources: sourceOrder.filter((src) => blockedBy.get(id)?.has(src)),
    });
    push(id, 'inactive', 'error', [...inactive]);
    push(id, 'not-found', 'error', [...notFound]);
    push(id, 'conflict', 'error', [...(conflicts.get(id) || [])]);
  }
  return { issues, conflicts };
}

// q must already be trimmed + lowercased.
export function modMatches(mods, id, q) {
  const m = mods.get(id);
  if (!m) return id.includes(q);
  return (
    m.name.toLowerCase().includes(q) ||
    m.id.includes(q) ||
    m.authors.some((a) => a.toLowerCase().includes(q))
  );
}

// Strip Unity rich-text tags (<color=...>, <b>, <size=...>) that mod authors
// put in About.xml descriptions.
export function cleanDescription(text) {
  return String(text || '')
    .replace(/<\/?(?:color|b|i|size|material|quad)(?:=[^>]*)?>/gi, '')
    .replace(/\r\n/g, '\n');
}

// Steam Workshop id of a mod: its folder name under workshop/content/294100
// in the real Steam library (source 'workshop'), or under <game>/Mods for a
// SteamCMD download (source 'steamcmd' or 'gog' by its marker's mode, copied
// in as Mods/<id>; electron/lib/steamCmd.js).
// Null for anything else (local, official, not found).
export function workshopId(mod) {
  return mod && (mod.source === 'workshop' || mod.source === 'steamcmd' || mod.source === 'gog') && /^\d+$/.test(mod.folder) ? mod.folder : null;
}

export function workshopUrls(mod) {
  const wid = workshopId(mod);
  if (!wid) return null;
  return {
    web: `https://steamcommunity.com/sharedfiles/filedetails/?id=${wid}`,
    steam: `steam://url/CommunityFilePage/${wid}`,
  };
}

// Workshop id of a "not found" list entry (id not among the scanned mods)
// whose id itself is a Steam Workshop id - the same id shapes the code above
// already treats as one: a bare numeric id (workshopId's /^\d+$/ folder check;
// pre-1.1 ModsConfig.xml/RimPy lists named Workshop mods by folder id) or the
// "workshop:<id>" sentinel from rentry import. Null otherwise. Subscribe is
// offered only for these (ModList.jsx context menu).
export function notFoundWorkshopId(id, mods) {
  if (!id || mods.has(id)) return null;
  const m = /^(?:workshop:)?(\d+)$/.exec(id);
  return m ? m[1] : null;
}

// "Check for missing Workshop mods" (Settings > Steam): every active-list row
// that's a not-found Workshop id (a numeric id or a workshop:<id> pending
// placeholder), in list order.
export function missingWorkshopRows(active, mods) {
  return active.filter((id) => notFoundWorkshopId(id, mods));
}

// Mod-acquisition modes (SCOPE.md §2a; settings.json steamAcquireVia,
// Settings > Steam), exclusive:
//   'steamcmd'   - SteamCMD downloads into <game>/Mods (temporary copy), Sync
//                  to Steam later makes it a real subscription. The default.
//   'steamworks' - subscribe straight through the Steam client; no SteamCMD,
//                  nothing in Mods.
//   'gog'        - SteamCMD downloads into <game>/Mods as the mod's permanent
//                  home; never synced (a GOG install has no Steam to sync to).
export const ACQUIRE_MODES = ['steamcmd', 'steamworks', 'gog'];

// The mode in effect: the stored choice (settings.json steamAcquireVia) when
// the user made one, else 'gog' for a GOG install (paths gameSource) and
// 'steamcmd' otherwise. Only an explicit choice is ever stored, so the GOG
// auto-pick follows the detected install until the user picks something.
export function effectiveAcquireVia(stored, gameSource) {
  if (ACQUIRE_MODES.includes(stored)) return stored;
  return gameSource === 'gog' ? 'gog' : 'steamcmd';
}

// Whether a mode downloads with SteamCMD into Mods (modes 'steamcmd', 'gog').
export function usesSteamCmd(acquireVia) {
  return acquireVia === 'steamcmd' || acquireVia === 'gog';
}

// Whether Subscribe can run at all for this mode: SteamCMD needs no Steam
// install, client or steamworks.js (so GOG works too); the Steam-client mode
// needs steamAvailable (main.js steam:available). The row must also be a
// notFoundWorkshopId entry.
export function subscribeReady(acquireVia, steamAvailable) {
  return usesSteamCmd(acquireVia) || !!steamAvailable;
}

// How Unsubscribe removes a scanned mod: 'steam' for a real Steam subscription
// (source 'workshop': unsubscribe, verify, then delete its folder), 'delete'
// for a SteamCMD download (source 'steamcmd' or 'gog': never subscribed, so
// only its files are deleted - an explicit user action, unlike Sync's
// automatic delete, which never touches a 'gog' copy), null for anything
// that isn't a Workshop mod.
export function unsubscribeKind(mod) {
  if (!workshopId(mod)) return null;
  return mod.source === 'steamcmd' || mod.source === 'gog' ? 'delete' : 'steam';
}

// Runs fn(item) for every item, at most `concurrency` at once: a worker pool,
// each runner pulling the next item off one shared iterator (so items start in
// order and a slow one never holds up the rest). fn must handle its own errors
// - one that throws rejects the whole pool. Resolves once every fn has.
export async function runPool(items, concurrency, fn) {
  const list = [...items];
  const queue = list.values(); // one shared iterator
  const runner = async () => {
    for (const item of queue) await fn(item);
  };
  await Promise.all(Array.from({ length: Math.max(1, Math.min(concurrency, list.length)) }, runner));
}

const errText = (err) => (err && err.message ? err.message : String(err));

// "Sync to Steam" (PLAN.md item 4): every SteamCMD-downloaded mod in the scan
// (source 'steamcmd': a <game>/Mods/<id> folder whose marker records the
// temporary 'steamcmd' mode; a 'gog'-mode copy is permanent and never
// touched) becomes a real Steam subscription, then its copy is deleted once
// Steam's own download is on disk (it takes over in the Workshop scan root).
// steam: { subscribe, isSubscribed, installInfo, deleteCopy, sleep, release?,
// log? } (App.jsx wires these to the IPC api).
//
// Two passes, because registering a subscription is fast (well under a second
// per item, even several at once) while waiting for Steam's download is slow
// and serialized by Steam itself (one Workshop download at a time, in
// subscription order - TODO.md entry 20):
//  1. Subscribe pass, up to `subscribeConcurrency` at once: subscribe, then
//     verify it took the way Unsubscribe does (re-check isSubscribed up to
//     `tries` times, `waitMs` apart), then release(wid) the item's Steam
//     helper (electron/lib/steam.js) so a long list doesn't pile them up. A
//     failure here is final for this run (failed). Every item is a real Steam
//     subscription within seconds of the sync starting, instead of trickling
//     in over the whole sync (PLAN.md item 4's accepted "not yet reflected in
//     Steam" window).
//  2. Install pass, over the items pass 1 verified, up to `concurrency` at
//     once: poll installInfo every `pollMs` until installed (up to
//     `timeoutMs`), then deleteCopy(mod.path). The copy is what the game
//     loads, so it's never deleted before Steam's is on disk: a download not
//     confirmed (timeout or installInfo error) keeps the copy and is pending.
//     So is an item whose delete didn't finish: deleteCopy (steamCmd.js
//     deleteItem) is best effort and reports a locked file as gone: false
//     rather than throwing - only gone: true counts as synced. The next sync
//     picks every pending item up again (subscribing is idempotent).
// A failed item is left untouched for the next sync; no retries within a run.
// onProgress(done, total), if given, runs once per item as its FINAL outcome
// lands (failed in pass 1, or synced/pending/failed in pass 2), never for the
// subscribe step alone, so "done" only counts items that are finished.
// Returns { total, synced, pending, failed }, each list in completion order.
export async function syncSteamCmdMods(mods, steam, { tries = 5, waitMs = 1000, pollMs = 2000, timeoutMs = 120_000, concurrency = 5, subscribeConcurrency = concurrency, onProgress } = {}) {
  const byWid = new Map();
  for (const m of mods.values()) {
    const wid = m.source === 'steamcmd' && workshopId(m);
    if (wid && !byWid.has(wid)) byWid.set(wid, m);
  }
  const log = steam.log || (() => {}); // per-mod decisions into volt.log (App.jsx passes rlog)
  const total = byWid.size;
  const synced = [];
  const pending = [];
  const failed = [];
  let done = 0; // items whose final outcome has landed
  const finish = () => {
    done++;
    if (onProgress) onProgress(done, total);
  };
  const fail = (wid, err) => {
    const error = errText(err);
    log(`sync ${wid}: FAILED - ${error}`);
    failed.push({ wid, error });
  };
  log(
    `sync: ${total} SteamCMD mod(s) to sync: ${[...byWid.keys()].join(', ')}` +
      (total ? `; subscribe pass up to ${Math.max(1, Math.min(subscribeConcurrency, total))} at once, then install pass up to ${Math.max(1, Math.min(concurrency, total))} at once` : ''),
  );

  // Pass 1: register every subscription.
  const verified = new Set();
  await runPool(byWid, subscribeConcurrency, async ([wid, mod]) => {
    try {
      await steam.subscribe(wid);
      log(`sync ${wid} (${mod.id}): subscribe call returned, verifying`);
      let ok = false;
      for (let i = 0; i < tries && !ok; i++) {
        if (i) await steam.sleep(waitMs);
        ok = await steam.isSubscribed(wid);
        log(`sync ${wid}: isSubscribed check ${i + 1}/${tries} -> ${ok}`);
      }
      if (!ok) throw new Error("Steam doesn't list it as subscribed");
      verified.add(wid);
      log(`sync ${wid}: verified subscribed (subscribe pass); its download is waited on in the install pass`);
    } catch (err) {
      fail(wid, err);
      finish();
    } finally {
      if (steam.release) {
        try {
          await steam.release(wid);
        } catch (err) {
          log(`sync ${wid}: couldn't release its Steam helper (${errText(err)}); it ends on its own idle timeout`);
        }
      }
    }
  });
  log(`sync: subscribe pass done: ${verified.size} of ${total} subscribed, ${failed.length} failed; waiting for Steam's downloads`);

  // Pass 2: wait for Steam's download, then delete the copy. Original order
  // (Steam downloads roughly in the order it was subscribed).
  await runPool([...byWid].filter(([wid]) => verified.has(wid)), concurrency, async ([wid, mod]) => {
    try {
      let installed = false;
      let last = '';
      try {
        for (let i = 0; i < Math.ceil(timeoutMs / pollMs) && !installed; i++) {
          if (i) await steam.sleep(pollMs);
          const st = await steam.installInfo(wid);
          installed = !!st.installed;
          const now = JSON.stringify(st);
          if (now !== last) log(`sync ${wid}: install status ${now}`);
          last = now;
        }
      } catch (err) {
        // can't confirm the download: keep the copy, like a timeout
        log(`sync ${wid}: install status check failed: ${errText(err)}`);
      }
      if (!installed) {
        log(`sync ${wid}: PENDING - subscribed but download not confirmed, SteamCMD copy kept`);
        pending.push(wid);
        return;
      }
      let r = null;
      let why = '';
      try {
        r = await steam.deleteCopy(mod.path);
      } catch (err) {
        why = errText(err);
      }
      if (r && r.gone === true) {
        synced.push(wid);
        log(`sync ${wid}: SUBSCRIBED and installed; deleted SteamCMD copy ${mod.path}`);
        return;
      }
      if (!why) {
        const skipped = (r && Array.isArray(r.skipped) && r.skipped) || [];
        why = `folder still on disk, ${skipped.length} item(s) couldn't be removed (locked or in use?)` +
          (skipped.length ? `: ${skipped.slice(0, 5).map((s) => `${s.path} (${s.error})`).join('; ')}${skipped.length > 5 ? `; +${skipped.length - 5} more` : ''}` : '');
      }
      log(`sync ${wid}: PENDING - subscribed and installed on Steam, but its SteamCMD copy ${mod.path} was NOT deleted (${why}); the next sync retries the delete`);
      pending.push(wid);
    } catch (err) {
      fail(wid, err);
    } finally {
      finish();
    }
  });
  log(`sync done: ${synced.length} synced, ${pending.length} pending, ${failed.length} failed of ${total}`);
  return { total, synced, pending, failed };
}

// Mode 2 ('steamworks') subscribe for one Workshop item, as Subscribe has
// always done it: subscribe (Steam also starts a high-priority download), then
// poll installInfo every `pollMs` until installed. Throws when it can't finish:
// Steam reports it not subscribed for `notSubscribedPolls` polls in a row
// (missing/private/removed item), or `timeoutMs` passes (Steam may still finish
// in the background). steam: { subscribe, installInfo, sleep, log?, now? }.
// Resolves the final (installed) status.
export async function steamSubscribeAndWait(wid, steam, { pollMs = 2000, timeoutMs = 120_000, notSubscribedPolls = 3 } = {}) {
  const log = steam.log || (() => {});
  const now = steam.now || Date.now;
  let st = await steam.subscribe(wid);
  let last = JSON.stringify(st);
  log(`subscribe ${wid}: status ${last}`);
  const deadline = now() + timeoutMs;
  let notSubscribed = 0;
  while (!st.installed) {
    notSubscribed = st.subscribed || st.downloading ? 0 : notSubscribed + 1;
    if (notSubscribed >= notSubscribedPolls) {
      throw new Error("Steam doesn't list it as subscribed (the item may not exist, or may be private or removed)");
    }
    if (now() >= deadline) {
      throw new Error(`Steam hadn't finished downloading it after ${timeoutMs / 1000} seconds (it may still finish in the background - rescan later)`);
    }
    await steam.sleep(pollMs);
    st = await steam.installInfo(wid);
    const cur = JSON.stringify(st);
    if (cur !== last) log(`subscribe ${wid}: status changed to ${cur}`);
    last = cur;
  }
  log(`subscribe ${wid}: done, installed`);
  return st;
}

// Imported "workshop:<id>" sentinels (modListIO.js parseRentryPageHtml: a
// rentry.co entry whose only id was its Workshop link; collection import, one
// per collection item) -> the scanned Workshop mod with that folder id.
// Unmatched sentinels are dropped and counted (skipped), or with keepUnmatched
// (collection import) kept as-is and counted (pending): the "pending" row that
// notFoundWorkshopId recognizes, so Subscribe can fetch it.
export function resolveWorkshopPlaceholders(ids, mods, { keepUnmatched = false } = {}) {
  const byWid = new Map();
  for (const m of mods.values()) {
    const wid = workshopId(m);
    if (wid) byWid.set(wid, m.id);
  }
  let skipped = 0;
  let pending = 0;
  const out = [];
  for (const id of ids) {
    if (!id.startsWith('workshop:')) out.push(id);
    else if (byWid.has(id.slice(9))) out.push(byWid.get(id.slice(9)));
    else if (keepUnmatched) {
      out.push(id);
      pending++;
    } else skipped++;
  }
  return { ids: out, skipped, pending };
}

// Ids for a shared export (rentry.co page, RimSort clipboard text): pending
// "workshop:<id>" placeholders (not a real mod yet) and "folder:<name>" ids (no
// packageId - nothing reading the list could write them to ModsConfig.xml) are
// left out. Same rule as Push and the RimPy .xml export, which drop them
// main-side (electron/lib/ids.js isWritableId; renderer can't import it).
export function exportableIds(ids) {
  return ids.filter((id) => !id.startsWith('workshop:') && !id.startsWith('folder:'));
}

// RimSort's clipboard format (also what rentry.co mod lists use): a header,
// then "Name [packageId][url]" per id; url is the Workshop page or "none".
// Not-found ids get a line too (name = id). Parsed back by electron/lib/modListIO.js.
export function buildRimSortText(ids, mods, appVersion, gameVersion) {
  return [
    `Created with VOLT v${appVersion || '?'}`,
    `RimWorld game version this list was created for: ${gameVersion || 'unknown'}`,
    `Total # of mods: ${ids.length}`,
    '',
    ...ids.map((id) => `${modName(mods, id)} [${id}][${workshopUrls(mods.get(id))?.web || 'none'}]`),
  ].join('\n');
}

// rentry.co page markdown, mirroring RimSort's own "export to rentry.co" layout
// (header, !!! info/note admonitions, numbered list). Workshop mods are numbered
// links followed by visible "{packageid: id}" text (inside the link's parens
// rentry.co hides it, and import reads the rendered page); everything else (official/local/not-found) goes in a
// "!!! warning" box. Parsed back by modListIO.js parseRentryMarkdownText.
// ponytail: no preview images (we only have local files); needs Steam API (PLAN.md item 4).
export function buildRentryMarkdown(ids, mods, appVersion, gameVersion) {
  return [
    '# RimWorld mod list',
    `Created with VOLT v${appVersion || '?'}`,
    ...(gameVersion ? [`Mod list was created for game version: \`${gameVersion}\``] : []),
    '!!! info Mods without a Steam Workshop link are shown in a highlighted box with their packageid.',
    '',
    `!!! note Mod list length: \`${ids.length}\``,
    '',
    ...ids.map((id, i) => {
      const name = modName(mods, id);
      const url = workshopUrls(mods.get(id))?.web;
      return url ? `${i + 1}. [${name}](${url}) {packageid: ${id}}` : `!!! warning ${i + 1}. ${name} {packageid: ${id}} `;
    }),
  ].join('\n');
}

// SteamCMD download status-bar row (App.jsx dl state, DownloadBar.jsx): one
// live event from main.js 'steamcmd:progress' (steamCmd.js
// createProgressParser) folded into the row's state. d: { wids, done: [wid]
// resolved ok or failed, failed: { wid: reason }, cur: { id, percent, speed }
// | null, ... }. Ids not in this row's wids are ignored; a re-resolved id
// (Resume re-runs every id; SteamCMD's cache answers the finished ones) counts
// once, and a later success clears its earlier failure.
export function applyDownloadEvent(d, ev) {
  if (!d || !ev || !d.wids.includes(ev.id)) return d;
  if (ev.type === 'progress') return { ...d, cur: { id: ev.id, percent: ev.percent, speed: ev.speedBytesPerSec } };
  if (ev.type !== 'item-done') return d;
  const failed = { ...d.failed };
  if (ev.ok) delete failed[ev.id];
  else failed[ev.id] = ev.message || 'failed';
  return {
    ...d,
    done: d.done.includes(ev.id) ? d.done : [...d.done, ev.id],
    failed,
    cur: d.cur && d.cur.id === ev.id ? null : d.cur,
  };
}
