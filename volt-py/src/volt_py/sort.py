"""One-click Sort (port of the rule-merge + auto-sort half of Electron's
src/renderer/src/lists.js: sortIdsByName, OFFICIAL_ORDER / sortOfficialIds /
officialIds, buildOrderConstraints, autoSortActive).

Pure Python, no Qt. Lists are lists of mod ids (lowercased packageIds);
`mods` is a dict id -> scanned mod (mods.py's dicts: "name", "source",
"load_before", "load_after", "mod_dependencies", ...).

Rule sources, highest priority first (standing convention, applies to any
future rule source too): user rules > community rules > About.xml >
dependency > alphabetical. Alphabetical (auto_sort_active's base rank) is
always the final fallback. User rules are VOLT-only (not in the Electron app):
the rules the user creates in the app, stored in settings.json's user_rules
(settings.py). A missing/failed community-rules fetch is just an empty dict -
it never blocks Sort (community_rules.py).
"""

import heapq

from .mods import natural_key, sort_key_name

# Core first, then the DLCs in release order; any other official content after, by name.
OFFICIAL_ORDER = [
    "ludeon.rimworld",
    "ludeon.rimworld.royalty",
    "ludeon.rimworld.ideology",
    "ludeon.rimworld.biotech",
    "ludeon.rimworld.anomaly",
    "ludeon.rimworld.odyssey",
]


def mod_name(mods: dict, mod_id: str) -> str:
    """lists.js modName: the mod's name, or the id itself for an unscanned id."""
    m = mods.get(mod_id)
    return m["name"] if m else mod_id


def sort_ids_by_name(ids, mods: dict) -> list[str]:
    """lists.js sortIdsByName: by name, leading [TAG]s ignored (sort_key_name),
    case-insensitive and numeric-aware. Uses mods.py's natural_key - the same
    stand-in for JS's Intl.Collator that the scan-time sort uses - so the
    Inactive pane and Sort's alphabetical fallback always agree. Stable."""
    return sorted(ids, key=lambda i: natural_key(sort_key_name(mod_name(mods, i))))


def _sort_official_ids(ids, mods: dict) -> list[str]:
    """Official ids (Core/DLC) in load order: OFFICIAL_ORDER first, any unknown
    official id after them, name-sorted (the second sort is stable)."""
    def rank(i: str) -> int:
        return OFFICIAL_ORDER.index(i) if i in OFFICIAL_ORDER else len(OFFICIAL_ORDER)

    return sorted(sort_ids_by_name(ids, mods), key=rank)


def official_ids(mods: dict) -> list[str]:
    """Every scanned official id (Core + DLC, from <game>/Data), in load order."""
    return _sort_official_ids([m["id"] for m in mods.values() if m.get("source") == "official"], mods)


def official_phrase(ids) -> str:
    """lists.js officialPhrase: status-text name for a set of official ids -
    "Core", "Core and 2 DLC", "1 DLC" (any non-Core official content counts
    as DLC; "" for no ids)."""
    core = OFFICIAL_ORDER[0] in ids
    dlc = len(ids) - (1 if core else 0)
    return " and ".join(p for p in ("Core" if core else "", f"{dlc} DLC" if dlc else "") if p)


def build_order_constraints(
    active, mods: dict, community_rules: dict | None, user_rules: list | None = None
) -> dict:
    """Every load-order rule among the active ids, from all four rule sources
    (user > community > About.xml > dependency), as a flat list:
    {"rules": [{"before", "after", "declared_by", "source"}], "overridden": N,
     "user_overridden": N, "dependency_conflicts": [{"dependent", "dependency",
     "sources"}]}.

    - before/after: ids, "before must load before after". declared_by: the
      mod whose own rule (a user rule entry naming it, its community-rules
      entry, its About.xml loadBefore/loadAfter, or its About.xml
      modDependencies) produced it - always one of before/after. source:
      "user" | "community" | "about" | "dependency".
    - User rules (highest priority, VOLT-only): each entry {"mod",
      "load_before", "load_after"} (its "id" is for the UI, ignored here)
      says its mod loads before every load_before id and after every
      load_after id. Several entries may name the same mod; each contributes
      its own rules, none are merged or collapsed. Two user rules that
      disagree with each other are both kept - the resulting cycle is broken
      by auto_sort_active like any other.
    - A community, About.xml or dependency rule that is the exact opposite of
      a user rule for the same pair is dropped (override-not-merge) and
      counted in `user_overridden` (a dependency rule beaten by a user rule
      goes there, not in dependency_conflicts). A rule contradicting both a
      user rule and a lower tier counts once, as user_overridden.
    - Only rules where both ids are in `active` count (packageIds compared
      case-insensitively); self-rules are ignored. A repeated active id's rules
      are read once. Explicit duplicates (e.g. A.loadBefore B plus B.loadAfter
      A) are all listed, each with its own declared_by; consumers dedupe as
      they need.
    - An About.xml rule that is the exact opposite of a community rule for the
      same pair is dropped (override-not-merge) and counted in `overridden`
      (only this: About.xml beaten by community; see user_overridden above).
    - Dependency rules (lowest priority): each active, scanned mod's
      mod_dependencies entry naming another active, scanned mod D implies
      "D before the mod" (declared_by: the dependent). It only fills gaps the
      explicit rules (user + surviving community + surviving About.xml) leave:
      when an explicit rule already orders the pair the same way, the
      dependency rule is redundant and not listed (so one misplaced pair is
      one rule, reported under the explicit rule's kind); when one orders it
      the opposite way, the dependency rule is dropped (override-not-merge) and recorded in
      `dependency_conflicts` (or counted in `user_overridden` when a user rule
      is among the opposing ones). A dependency named twice by the same mod
      counts once.
    - dependency_conflicts: one entry per dropped (dependent, dependency) pair
      that no user rule opposes: `dependent` needs `dependency`, but a
      community/About.xml rule says dependent loads before dependency.
      sources: the source(s) of those conflicting explicit rules, "community"
      before "about", no repeats.

    `community_rules`: lowercased id -> {"load_after": [...], "load_before": [...]}
    (community_rules.py); None or {} when unavailable.
    `user_rules`: settings.json's user_rules list, packageIds as the user typed
    them (matched case-insensitively here like every other tier); None or []
    when there are none - then the result is exactly the 3-tier (Electron)
    one, plus user_overridden 0.
    Single source of truth for auto_sort_active's edges (and, once ported,
    validateActive's order violations): a new rule source only needs adding here.
    """
    community_rules = community_rules or {}
    on = dict.fromkeys(active or [])  # ordered set: JS `new Set(active)`

    def lookup(pid) -> str | None:
        i = str(pid).strip().lower()
        return i if i in on else None

    rules: list[dict] = []

    def add(before, after, declared_by, source) -> None:
        if before is None or after is None or before == after:
            return
        rules.append({"before": before, "after": after, "declared_by": declared_by, "source": source})

    def id_list(value) -> list:
        # settings.json is hand-editable: only a list's string items count.
        return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []

    # User rules first, in list order; remember each rule's direction
    # ((a, b): a before b).
    for entry in user_rules or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("mod"), str):
            continue
        i = lookup(entry["mod"])
        if i is None:
            continue
        for pid in id_list(entry.get("load_before")):
            add(i, lookup(pid), i, "user")
        for pid in id_list(entry.get("load_after")):
            add(lookup(pid), i, i, "user")
    user_edges = {(r["before"], r["after"]) for r in rules}

    # A user rule wins outright over any conflicting lower-tier rule for the
    # same pair: that rule is dropped, not merged, and counted here.
    user_overridden = 0

    def beaten_by_user(before, after) -> bool:
        nonlocal user_overridden
        if before is not None and after is not None and (after, before) in user_edges:
            user_overridden += 1
            return True
        return False

    # Then community rules.
    for i in on:
        c = community_rules.get(i)
        if not c:
            continue
        for pid in c.get("load_before") or []:
            if not beaten_by_user(i, lookup(pid)):
                add(i, lookup(pid), i, "community")
        for pid in c.get("load_after") or []:
            if not beaten_by_user(lookup(pid), i):
                add(lookup(pid), i, i, "community")
    community_edges = {(r["before"], r["after"]) for r in rules if r["source"] == "community"}

    # Then About.xml. A community rule wins outright over a conflicting
    # About.xml rule for the same pair: the About.xml rule is dropped, not
    # merged. Revisit if override-not-merge proves too blunt.
    overridden = 0

    def add_about(before, after, declared_by) -> None:
        nonlocal overridden
        if beaten_by_user(before, after):
            return
        if before is not None and after is not None and (after, before) in community_edges:
            overridden += 1
            return
        add(before, after, declared_by, "about")

    for i in on:
        m = mods.get(i)
        if not m:
            continue
        for pid in m.get("load_before") or []:
            add_about(i, lookup(pid), i)
        for pid in m.get("load_after") or []:
            add_about(lookup(pid), i, i)

    # Every surviving explicit edge (user + community + About.xml) -> its
    # source(s), in priority order.
    explicit_edges: dict[tuple[str, str], list[str]] = {}
    for r in rules:
        sources = explicit_edges.setdefault((r["before"], r["after"]), [])
        if r["source"] not in sources:
            sources.append(r["source"])

    # Finally mod_dependencies: dependency before dependent, where no explicit
    # rule already orders the pair.
    dependency_conflicts: list[dict] = []
    for i in on:
        m = mods.get(i)
        if not m:
            continue
        seen: set[str] = set()
        for pid in m.get("mod_dependencies") or []:
            dep = lookup(pid)
            if dep is None or dep == i or dep not in mods or dep in seen:
                continue
            seen.add(dep)
            if (dep, i) in explicit_edges:
                continue  # already ordered this way
            against = explicit_edges.get((i, dep))
            if against and "user" in against:
                user_overridden += 1  # a user rule says the opposite: it wins, no conflict entry
            elif against:
                dependency_conflicts.append({"dependent": i, "dependency": dep, "sources": list(against)})
            else:
                add(dep, i, i, "dependency")
    return {
        "rules": rules,
        "overridden": overridden,
        "user_overridden": user_overridden,
        "dependency_conflicts": dependency_conflicts,
    }


def auto_sort_active(
    active, mods: dict, community_rules: dict | None = None, user_rules: list | None = None
) -> dict:
    """One-click Sort: reorders the active list by the user's own rules
    (VOLT-only), community rules, each mod's own About.xml
    loadAfter/loadBefore, and its About.xml modDependencies (a dependency
    loads before the mod needing it).

    Returns {"active", "unresolved", "overridden", "user_overridden",
    "dependency_conflicts", "rules"}: the same ids (none added, dropped or
    duplicated) in the new order; the number of ordering constraints that had
    to be dropped to break cycles; the number of About.xml rules dropped
    because a community rule says the opposite; the number of community/
    About.xml/dependency rules dropped because a user rule says the opposite
    (not in the JS); build_order_constraints' dependency_conflicts list (the
    JS returns only its length); and the merged rule list (for logging - not
    in the JS). With no user_rules the result is the JS one (user_overridden 0).

    - One topological sort over every active id. A constraint "A before B"
      exists when A.loadBefore names B or B.loadAfter names A (or, lowest
      priority, B's modDependencies names A), whatever A and B are, official
      included. Rules naming a mod that isn't in the active list are ignored.
      Duplicate rules count once.
    - Official mods (Core/DLC) keep their relative order through a synthetic
      chain: each one in official order (Core, DLCs by release, unknown
      official ids by name) must load after the previous one. A real rule can
      still put another mod before or between them (e.g. a mod whose
      loadBefore names Core) - not a hard partition, so Harmony can sort ahead
      of Core.
    - Base rank: official mods first in that order, then every other id by
      name. A mod's effective rank is the lowest base rank of anything it must
      load before (itself included), so a mod that has to precede Core is
      pulled up to just before Core instead of dragging every alphabetically
      earlier mod ahead of Core with it.
    - Kahn's algorithm, always emitting the ready mod (no unplaced
      predecessor) with the lowest (effective rank, base rank). With no rules
      at all the result is Core, DLCs in release order, then everything else
      by name. (The JS rescans all n mods per placement; a heap of ready mods
      keyed the same way picks the identical mod each step, just O(n log n).)
    - Cycle (nothing ready): follow unplaced predecessors from the
      lowest-ranked unplaced mod, always taking the lowest-ranked predecessor,
      until a mod repeats; the mods between the repeats form a cycle. Its
      lowest-ranked member is placed anyway, and every rule from a
      still-unplaced mod into it is dropped and counted in `unresolved`. Mods
      merely waiting behind a cycle keep their rules. Which edge is dropped
      ignores the rule's tier.
    """
    ids = list(active or [])

    def is_official(i: str) -> bool:
        m = mods.get(i)
        return bool(m) and m.get("source") == "official"

    # Base-rank order: index in `ranked` is the base rank.
    ranked = _sort_official_ids([i for i in ids if is_official(i)], mods) + sort_ids_by_name(
        [i for i in ids if not is_official(i)], mods
    )
    n = len(ranked)
    index_of: dict[str, int] = {}  # id -> first position in ranked
    for pos, i in enumerate(ranked):
        index_of.setdefault(i, pos)
    succ: list[set[int]] = [set() for _ in range(n)]
    pred: list[set[int]] = [set() for _ in range(n)]

    def add_edge(a: int | None, b: int | None) -> None:
        if a is None or b is None or a == b or b in succ[a]:
            return
        succ[a].add(b)
        pred[b].add(a)

    # Synthetic chain keeping official mods in their own order.
    prev_official = None
    for pos, i in enumerate(ranked):
        if index_of[i] != pos or not is_official(i):
            continue
        if prev_official is not None:
            add_edge(prev_official, pos)
        prev_official = pos
    # Rules (user + community + About.xml + dependency), from the one shared builder.
    constraints = build_order_constraints(ids, mods, community_rules, user_rules)
    for r in constraints["rules"]:
        add_edge(index_of.get(r["before"]), index_of.get(r["after"]))

    # Effective rank: lowest base rank reachable along successors. Walking
    # predecessors from each rank in ascending order assigns every mod once.
    eff = [-1] * n
    for r in range(n):
        if eff[r] >= 0:
            continue
        eff[r] = r
        stack = [r]
        while stack:
            for p in pred[stack.pop()]:
                if eff[p] < 0:
                    eff[p] = r
                    stack.append(p)

    def key(i: int) -> tuple[int, int]:
        return (eff[i], i)

    placed = [False] * n
    waiting = [len(p) for p in pred]  # unplaced predecessors per mod
    ready = [key(i) for i in range(n) if waiting[i] == 0]
    heapq.heapify(ready)
    out: list[str] = []
    unresolved = 0

    def lowest_unplaced(candidates) -> int:
        return min((i for i in candidates if not placed[i]), key=key, default=-1)

    while len(out) < n:
        if ready:
            nxt = heapq.heappop(ready)[1]
        else:
            # Every unplaced mod waits on another unplaced one: find a cycle.
            cur = lowest_unplaced(range(n))
            step: dict[int, int] = {}
            path: list[int] = []
            while cur not in step:
                step[cur] = len(path)
                path.append(cur)
                cur = lowest_unplaced(pred[cur])
            nxt = lowest_unplaced(path[step[cur]:])
            unresolved += waiting[nxt]
            waiting[nxt] = 0
        placed[nxt] = True
        out.append(ranked[nxt])
        for s in succ[nxt]:
            if not placed[s]:
                waiting[s] -= 1
                if waiting[s] == 0:
                    heapq.heappush(ready, key(s))

    return {
        "active": out,
        "unresolved": unresolved,
        "overridden": constraints["overridden"],
        "user_overridden": constraints["user_overridden"],
        "dependency_conflicts": constraints["dependency_conflicts"],
        "rules": constraints["rules"],
    }
