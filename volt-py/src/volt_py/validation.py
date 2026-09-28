"""Live load-order validation (port of Electron's src/renderer/src/lists.js
validateActive; RIMWORLD.md "Validation"): warn-only, never blocks
Save/Push.

Pure Python, no Qt. Ids are lowercased packageIds; `mods` is a dict id ->
scanned mod (mods.py's dicts: "mod_dependencies", "incompatible_with",
"load_before", "load_after", ...). A pure function of the active list, the
scanned mods and the rules - cheap enough to recompute on every
active-list change.

Differences from the JS, all deliberate (not bugs):
- Field names are snake_case throughout: the scanned mod's
  "incompatible_with" / "mod_dependencies" (JS incompatibleWith /
  modDependencies), each rule's "declared_by", build_order_constraints'
  "dependency_conflicts", and the issue's own "mod_id" / "rule_sources"
  (JS modId / ruleSources). Kind and severity strings are verbatim.
- One more rule tier: user rules (VOLT-only, settings.json user_rules),
  passed straight through to sort.build_order_constraints - the single
  source of truth for order rules shared with Sort, never recomputed here.
  With user_rules None/[] the result is exactly the JS (3-tier) one.
  "rule_sources" is ordered by the same priority Sort uses, "user" first
  (JS: ['community', 'about']). build_order_constraints never lists a
  dependency conflict a user rule opposes (a user rule beats the
  dependency tier outright and is counted in its user_overridden instead),
  so in practice "user" does not appear there today; it is kept in the
  order so the tier can't be silently dropped if that ever changes.
- "conflicts" values are sets (JS Set); the issue "targets" for
  inactive / not-found / conflict keep the JS insertion order (first
  mention), tracked separately because a Python set is unordered.
"""

from .sort import build_order_constraints

# Priority order of "rule_sources" on an order-dependency-conflict issue:
# the explicit tiers above the dependency tier, highest first (sort.py).
RULE_SOURCE_ORDER = ("user", "community", "about")


def _norm(pid) -> str:
    """lists.js norm: String(pid).trim().toLowerCase()."""
    return str(pid).strip().lower()


def validate_active(
    active: list[str], mods: dict, community_rules: dict | None = None, user_rules: list | None = None
) -> dict:
    """lists.js validateActive. Returns {"issues": [...], "conflicts": {mod_id: {other_ids}}}.

    - issues: one entry per (active mod, kind), grouped by mod in active
      order (first occurrence of a repeated id), warnings before errors
      within a mod, in this kind order:
        {"key": "<mod_id>|<kind>", "mod_id", "kind", "severity", "targets": [id]}
      plus "rule_sources" on order-dependency-conflict only. Kinds:
        order-before      (warning) this mod's own loadBefore rule (user,
                          community or About.xml) names these active mods,
                          but it currently loads after them.
        order-after       (warning) same, for its own loadAfter rules: it
                          currently loads before these.
        order-dependency  (warning) mod_dependencies that are active but
                          currently load after this mod (the "dependency"
                          rules; a pair an explicit rule already orders the
                          same way is reported under that rule's kind
                          instead). Sort fixes these.
        order-dependency-conflict  (warning) mod_dependencies that are active
                          and load after this mod, where Sort won't move them
                          because an explicit rule says this mod loads before
                          them (build_order_constraints' dependency_conflicts).
                          rule_sources: those rules' sources over all targets,
                          RULE_SOURCE_ORDER, no repeats.
        inactive          (error) mod_dependencies scanned but not active.
        not-found         (error) mod_dependencies no scanned mod provides.
        conflict          (error) incompatible_with pairs where both mods are
                          active; symmetric, both mods get an entry.
      Order kinds only compare mods that are active and scanned, are keyed
      by the mod that declared the rule (for a dependency rule: the
      dependent), and their targets are in active-list order. An issue is
      only emitted with at least one target. Active ids not scanned get no
      issues of their own.
    - conflicts: the active conflict pairs, both ways.
    """
    active = active or []
    on = dict.fromkeys(active)  # ordered set: JS `new Set(active)`
    pos: dict[str, int] = {}  # id -> first position in the active list
    for i, mod_id in enumerate(active):
        pos.setdefault(mod_id, i)

    # Ordered "sets" (dict keys) so every target list keeps the JS
    # insertion order.
    def add_to(table: dict, a: str, b: str) -> None:
        table.setdefault(a, {})[b] = None

    conflicts: dict[str, dict[str, None]] = {}
    for mod_id in on:
        m = mods.get(mod_id)
        for pid in (m.get("incompatible_with") if m else None) or []:
            other = _norm(pid)
            if not other or other == mod_id or other not in on:
                continue
            add_to(conflicts, mod_id, other)
            add_to(conflicts, other, mod_id)

    # Order violations, keyed by the declaring mod (for a dependency rule: the dependent).
    should_before: dict[str, dict[str, None]] = {}  # declarer -> ids it should load before
    should_after: dict[str, dict[str, None]] = {}  # declarer -> ids it should load after
    dep_later: dict[str, dict[str, None]] = {}  # dependent -> active dependencies loading after it
    constraints = build_order_constraints(active, mods, community_rules, user_rules)
    for r in constraints["rules"]:
        before, after = r["before"], r["after"]
        if before not in mods or after not in mods or pos[before] < pos[after]:
            continue
        if r["source"] == "dependency":
            add_to(dep_later, after, before)
        elif r["declared_by"] == before:
            add_to(should_before, before, after)
        else:
            add_to(should_after, after, before)

    # Dependency orderings Sort won't apply (a conflicting explicit rule),
    # where the dependency currently loads after its dependent.
    dep_blocked: dict[str, dict[str, None]] = {}  # dependent -> such dependencies
    blocked_by: dict[str, dict[str, None]] = {}  # dependent -> conflicting rule sources
    for c in constraints["dependency_conflicts"]:
        if pos[c["dependency"]] < pos[c["dependent"]]:
            continue
        add_to(dep_blocked, c["dependent"], c["dependency"])
        for src in c["sources"]:
            add_to(blocked_by, c["dependent"], src)

    def by_pos(table: dict, mod_id: str) -> list[str]:
        return sorted(table.get(mod_id, ()), key=pos.__getitem__)

    issues: list[dict] = []

    def push(mod_id: str, kind: str, severity: str, targets: list[str], **extra) -> None:
        if targets:
            issues.append({"key": f"{mod_id}|{kind}", "mod_id": mod_id, "kind": kind,
                           "severity": severity, "targets": targets, **extra})

    for mod_id in on:
        m = mods.get(mod_id)
        if not m:
            continue
        inactive: dict[str, None] = {}
        not_found: dict[str, None] = {}
        for pid in m.get("mod_dependencies") or []:
            dep = _norm(pid)
            if not dep or dep == mod_id or dep in on:
                continue  # active ones: order rules above
            (inactive if dep in mods else not_found)[dep] = None
        push(mod_id, "order-before", "warning", by_pos(should_before, mod_id))
        push(mod_id, "order-after", "warning", by_pos(should_after, mod_id))
        push(mod_id, "order-dependency", "warning", by_pos(dep_later, mod_id))
        sources = blocked_by.get(mod_id, {})
        push(mod_id, "order-dependency-conflict", "warning", by_pos(dep_blocked, mod_id),
             rule_sources=[src for src in RULE_SOURCE_ORDER if src in sources])
        push(mod_id, "inactive", "error", list(inactive))
        push(mod_id, "not-found", "error", list(not_found))
        push(mod_id, "conflict", "error", list(conflicts.get(mod_id, ())))

    return {"issues": issues, "conflicts": {k: set(v) for k, v in conflicts.items()}}
