"""Mod-list row decorations: the official badge, outdated marking, the
selected mod's dependency highlighting and the load-order validation marks
(port of Electron's lists.js isOutdated / buildDependencyIndex and the flags
+ notes ModList.jsx's Row derives from them; the validation flags come from
validation.validate_active, derived by the screen).

Pure Python, no Qt: screens/mod_list.py paints RowDecor, the RimWorld main
screen computes it from the scanned mods (ids are lowercased packageIds;
`mods` is a dict id -> scanned mod, mods.py's dicts: "name", "package_id",
"source", "supported_versions", "mod_dependencies", ...).
"""

import re
from typing import NamedTuple


class RowDecor(NamedTuple):
    """What a pane row shows beyond its name and color swatch (ModList.jsx
    RowLabel / RowView props of the same names):
      official    the "L" badge (.row-badge): source 'official', Core + DLC
      outdated    the name in --danger (.row-name.outdated): is_outdated
      dependency  the selected mod depends on this one (.row.dependency)
      dependent   this one depends on the selected mod (.row.dependent)
      warning     the Active row's warning triangle (RowIssues: a warning-
                  severity validation issue of this mod)
      error       the Active row's red cross (RowIssues: an error-severity
                  issue), always right of the triangle
      conflict    an active hard conflict (incompatibleWith, validate_active's
                  "conflicts"): the name in --danger like outdated, plus the
                  .row.conflict --warn outline
      pending     a "not found" row whose id is a Workshop id
                  (mod_list_io.not_found_workshop_id), not downloading:
                  .row.pending's dashed --border outline, the name in the
                  normal color with a muted "(pending)" after it, and the
                  inline Subscribe button (.row-subscribe) at the right end
      downloading such a row with a Subscribe under way (the screen's
                  `downloading` set): .row.downloading's 0.6 opacity, the
                  name in --danger (.row-name.missing) with a muted
                  "⟳ downloading…" after it, no outline, no button
      not_found   the id has no scanned mod at all (RowLabel's !mod: a
                  load-order / imported id of a removed, renamed or never-
                  installed mod, kept in Active by _show_lists as Electron's
                  reconcileLists keeps it). Alone - neither pending nor
                  downloading - it's RowLabel's plain missing branch: the
                  name in --danger (.row-name.missing) with a muted
                  "(not found)" after it, no opacity, outline or button.
                  Also set on every pending / downloading row (they're
                  not-found rows too); those two decide the look then.
      dds_leftover the muted ".dds" badge right after the name
                  (.row-badge.dds-leftover): the scan's dds_leftover, a
                  folder of only .dds textures (a texture-compression
                  leftover, not a real mod). Never on official content.
      row_warn    the bold --warn "!" after the name - after the .dds badge
                  when both apply (.row-warn): the scanned mod's `warnings`
                  (mods.py: no packageId, a duplicate copy ignored) is
                  non-empty. Scanned mods only, so never with a name suffix;
                  every dds_leftover mod has one (no packageId)."""

    official: bool = False
    outdated: bool = False
    dependency: bool = False
    dependent: bool = False
    warning: bool = False
    error: bool = False
    conflict: bool = False
    pending: bool = False
    downloading: bool = False
    not_found: bool = False
    dds_leftover: bool = False
    row_warn: bool = False


NO_DECOR = RowDecor()

# ModList.jsx: the .row-badge's own title (folded into the row tooltip here).
OFFICIAL_NOTE = "Official content (Core/DLC), not a mod."
# ModList.jsx: the .row-badge.dds-leftover's own title (likewise folded in).
DDS_LEFTOVER_NOTE = "Only .dds texture files - likely a texture-compression leftover, not a real mod."
# ModList.jsx RowLabel: the muted <em> after a not-found row's name.
PENDING_SUFFIX = "(pending)"
DOWNLOADING_SUFFIX = "\u27f3 downloading\u2026"
NOT_FOUND_SUFFIX = "(not found)"


def name_is_red(decor: RowDecor) -> bool:
    """The row's name is --danger: ModList.jsx RowLabel's .row-name.outdated
    (outdated || conflict) for a scanned mod, .row-name.missing for a
    not-found row that isn't pending (downloading, or a plain not-found
    id). A pending row's name keeps the normal color (RowLabel's pending
    branch ignores outdated / conflict)."""
    if decor.downloading:
        return True
    return not decor.pending and (decor.not_found or decor.outdated or decor.conflict)


def name_suffix(decor: RowDecor) -> str | None:
    """RowLabel's muted <em> after the name: "(pending)" / "\u27f3 downloading\u2026"
    / "(not found)" (the missing branch's other text: a not-found row that
    is neither pending nor downloading), None for a scanned mod."""
    if decor.pending:
        return PENDING_SUFFIX
    if decor.downloading:
        return DOWNLOADING_SUFFIX
    if decor.not_found:
        return NOT_FOUND_SUFFIX
    return None

_NO_IDS: frozenset = frozenset()
# lists.js majorMinor: /^(\d+)\.(\d+)/ - JS \d is ASCII-only, hence re.ASCII.
_MAJOR_MINOR = re.compile(r"(\d+)\.(\d+)", re.ASCII)


def major_minor(v) -> tuple[int, int] | None:
    """lists.js majorMinor: RimWorld "major.minor" of a version string
    ("1.6.4871 rev590" -> (1, 6)), or None."""
    m = _MAJOR_MINOR.match(str("" if v is None else v).strip())
    return (int(m[1]), int(m[2])) if m else None


def is_outdated(mod: dict | None, game_version) -> bool:
    """lists.js isOutdated: the mod declares supported_versions and the
    highest of them (major.minor only) is below the installed game's
    major.minor. False whenever either side is unknown or unparseable -
    never marked on doubt (unparseable entries are skipped; none left ->
    False)."""
    game = major_minor(game_version)
    if game is None or mod is None:
        return False
    versions = mod.get("supported_versions")
    if not isinstance(versions, (list, tuple)):
        return False
    best = max((mm for v in versions if (mm := major_minor(v)) is not None), default=None)
    return best is not None and best < game


def build_dependency_index(mods: dict) -> dict[str, dict[str, set[str]]]:
    """lists.js buildDependencyIndex: the hard-dependency index from About.xml
    modDependencies, over every scanned mod:
      {"depends_on": {id: {ids it depends on}},
       "depended_on_by": {id: {ids depending on it}}}
    A dependency naming an unscanned mod, or the mod itself, is left out (an
    unscanned dependency is validation's to report). Pure function of
    `mods`, so callers memoize it per scan."""
    depends_on: dict[str, set[str]] = {}
    depended_on_by: dict[str, set[str]] = {}
    for m in mods.values():
        mod_id = m["id"]
        for pid in m.get("mod_dependencies") or []:
            dep = str(pid).strip().lower()
            if not dep or dep == mod_id or dep not in mods:
                continue
            depends_on.setdefault(mod_id, set()).add(dep)
            depended_on_by.setdefault(dep, set()).add(mod_id)
    return {"depends_on": depends_on, "depended_on_by": depended_on_by}


def selection_highlights(index: dict, selected_id: str | None) -> tuple[frozenset, frozenset]:
    """App.jsx dependencyIds / dependentIds for the selected mod: (the ids it
    depends on, the ids depending on it), from build_dependency_index's
    result. Both empty with nothing selected."""
    if not selected_id:
        return _NO_IDS, _NO_IDS
    return (
        frozenset(index["depends_on"].get(selected_id, ())),
        frozenset(index["depended_on_by"].get(selected_id, ())),
    )


def row_tooltip(
    mod: dict | None, mod_id: str, decor: RowDecor, conflict_names: list[str] | None = None, title: str | None = None
) -> str:
    """ModList.jsx RowView's title: the mod's name and packageId, then one
    line per note (outdated, required by / requires the selected mod,
    incompatible with: `conflict_names`, the names of the active mods it
    conflicts with - shown when decor.conflict) - plus the official / .dds
    badge's own title and the "!" mark's (one line per mod warning), which
    the Electron app shows only over the badge / mark. An
    unscanned id is just the id - after its Workshop title `title`, when
    it's a not-found Workshop id whose title is known (`${pendingTitle}\n${id}`)."""
    if mod is None:
        lines = [title, mod_id] if title else [mod_id]
    else:
        lines = [mod["name"]]
        if mod.get("package_id"):
            lines.append(mod["package_id"])
    if decor.official:
        lines.append(OFFICIAL_NOTE)
    if decor.dds_leftover:
        lines.append(DDS_LEFTOVER_NOTE)
    if decor.row_warn and mod is not None:
        lines.extend(mod.get("warnings") or ())  # .row-warn's title: warnings.join('\n')
    if decor.outdated and mod is not None:
        versions = ", ".join(str(v) for v in mod.get("supported_versions") or [])
        lines.append(f"Outdated: supports {versions} only")
    if decor.dependency:
        lines.append("Required by the selected mod")
    if decor.dependent:
        lines.append("Requires the selected mod")
    if decor.conflict and conflict_names:
        lines.append(f"Incompatible with: {', '.join(conflict_names)}")
    return "\n".join(lines)
