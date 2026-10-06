"""Mod conflicts for Thunderstore/BepInEx profiles (troubleshooting phase 1,
TODO #57; THUNDERSTORE.md): advice only - nothing here changes a profile.
The manager screen (screens/bepinex_main_screen.py) turns profile_issues()'
dicts into rows' tooltips / icons, the "⚠ N · ✕ M" count and the Warnings
and errors window (screens/bepinex_issues_window.py), beside
bepinex_load_orders.dependency_issues' (the same dict shape).

Only Active, switched-on mods are checked. Four kinds, one issue per mod
pair (the strongest wins: incompatible > two_versions > duplicate_plugin >
duplicate_file).
Evidence-derived only: no bundled or online list of known conflicting pairs
(the phase-1 conflicts.json was retired 2026-10-04, user decision); the one
exception is HARD_CLASH_PAIRS, which only raises a found two_versions pair
to an error.
  - "incompatible" (error): a plugin declares [BepInIncompatibility(guid)]
    and another switched-on package's plugin has that GUID. BepInEx then
    refuses to load the DECLARING plugin ("Could not load [WeatherRegistry
    0.8.8] because it is incompatible with: Ozzymops.DisableStormyWeather");
    the other one loads. Matched GUID to GUID, never by package name.
  - "two_versions" (warning; error for a HARD_CLASH_PAIRS pair, the game then
    never reaches the main menu; 0.6.49, library-clash Phase A): a pair is both
    a duplicate_plugin and a duplicate_file hit, and neither package declares
    the other a dependency - two versions of one mod are on (DawnLib vs
    DawnLibExperimental). The runtime loads one assembly per name, so mods
    built for the other copy break. Detection is game-agnostic, no pair list.
    # ponytail: stand-in for "same assembly name, differing bytes" (the
    # same-named DLL file); a renamed DLL with an unchanged assembly name is
    # missed. Phase B (assembly names from the type index) if one turns up.
    The issue carries what "which one to keep" needs: both sides'
    switched-on dependents, package and plugin versions, and "keep" (the
    one the other mods need, else the newer one, else None).
  - "duplicate_plugin" (warning): two packages carry a plugin with the same
    GUID (a re-upload of the same mod; or a fork declaring the original a
    dependency, e.g. LethalLevelLoaderUpdated, which stays this kind).
  - "duplicate_file" (warning): two packages put a .dll with the same file
    name under BepInEx/{plugins,patchers,core,monomod} and the contents
    differ (size, then sha1). Identical copies are harmless and stay silent
    (HookGenPatcher / AutoHookGenPatcher's MonoMod.dll).

GUIDs come from a pure byte scan of each package's plugin DLLs
(extract_plugin_info; no metadata reader, no new dependency): ECMA-335
custom-attribute blobs - the 01 00 prolog, length-prefixed UTF-8 strings,
00 00 (no named arguments). [BepInPlugin(guid, name, version)] is the
3-string blob whose last string is a version; [BepInIncompatibility(guid)]
a 1-string blob, read only from DLLs that mention BepInIncompatibility at
all, minus strings the DLL also holds as a whole name (an assembly it
references: IgnoresAccessChecksTo blobs look the same), and only ever
reported when it equals an installed plugin's GUID. scan_package() reads a mod's files under
their own names or their .disabled twins, so a toggle never changes the
result; the screen caches scans by scan_key() and runs them (and
file_conflicts' hashing) off the GUI thread.

Qt-free; nothing here raises - an unreadable file or list is skipped and
logged. tools/checks/volt_py_bepinex_conflicts.py pins it.
"""

import hashlib
import re
import time
from pathlib import Path

from . import bepinex_install as bx
from .applog import clip, log
from .bepinex_load_orders import _declared_dependencies

BLOB_MAX = 64 * 1024 * 1024  # skip bigger files (no plugin DLL is near this)
TREE_DIRS = ("BepInEx/plugins/",)  # where plugin DLLs (GUIDs) are scanned
CODE_DIRS = ("BepInEx/plugins/", "BepInEx/patchers/", "BepInEx/core/", "BepInEx/monomod/")  # same-file check
KIND_RANK = ("incompatible", "two_versions", "duplicate_plugin", "duplicate_file")  # one issue per pair, first wins
SEVERITY = {"incompatible": "error", "two_versions": "warning", "duplicate_plugin": "warning", "duplicate_file": "warning"}
# ponytail: hardcoded known pairs only; user wants a generic rework when the next library-mod hard clash appears (memory/TODO.md #60)
HARD_CLASH_PAIRS = {  # two_versions pairs (package full_names, either order) seen to stop the game: severity "error"
    frozenset(("TeamXiaolan-DawnLib", "TeamXiaolan-DawnLibExperimental")),  # Lethal Company, hardware 2026-10-06
}
TEXT = {  # the row tooltip line; {dep} = the other mod's name as on screen
    "incompatible": "Won't load: it's incompatible with {dep}.",
    "two_versions": "Another version of this mod is also on: {dep}.",
    "duplicate_file": "Shares files with {dep} that differ: may conflict.",
    "duplicate_plugin": "Looks like a second copy of {dep}.",
}

_PROLOG = re.compile(rb"\x01\x00(?=[\x01-\x7e])")
_ID = re.compile(r"^[\w.\-]+$")
_VERSION = re.compile(r"^\d+(\.\d+){1,3}[\w.+-]*$")


def _ser_strings(data: bytes, pos: int, limit: int = 3) -> list[str] | None:
    """The 1..`limit` SerStrings (1-byte length 1..0x7e, UTF-8) at `pos`,
    when followed by 00 00 (no named arguments); else None."""
    out: list[str] = []
    while len(out) < limit:
        n = data[pos] if pos < len(data) else 0
        if not 1 <= n <= 0x7E or pos + 1 + n > len(data):
            return None
        try:
            out.append(data[pos + 1:pos + 1 + n].decode("utf-8"))
        except UnicodeDecodeError:
            return None
        pos += 1 + n
        if data[pos:pos + 2] == b"\x00\x00":
            return out
    return None


def extract_plugin_info(data: bytes) -> dict:
    """{"guids": [...], "incompat": [...], "versions": {guid: version}} read
    from one DLL's bytes (module docstring). "incompat" holds CANDIDATES
    only - match them against installed GUIDs, never report one on its own.
    "versions" = each GUID's BepInPlugin version (BepInEx keeps the highest
    per GUID)."""
    guids: list[str] = []
    incompat: list[str] = []
    versions: dict[str, str] = {}
    plugin = b"BepInPlugin" in data
    declares = b"BepInIncompatibility" in data
    if not (plugin or declares):
        return {"guids": guids, "incompat": incompat, "versions": versions}
    for m in _PROLOG.finditer(data):
        strings = _ser_strings(data, m.end())
        if not strings or not _ID.match(strings[0]):
            continue
        if plugin and len(strings) == 3 and _VERSION.match(strings[2]):
            if strings[0] not in guids:
                guids.append(strings[0])
                versions[strings[0]] = strings[2]
        elif declares and len(strings) == 1 and len(strings[0]) >= 3 and strings[0] not in incompat:
            incompat.append(strings[0])
    # A candidate that is also a whole name in the DLL's string heap (an
    # assembly it references, a namespace) is another 1-string attribute -
    # IgnoresAccessChecksTo("MrovLib") in WeatherRegistry.dll, where MrovLib's
    # GUID is "MrovLib" too - never an incompatibility: a mod can't need an
    # assembly and refuse to load beside it.
    # ponytail: heuristic; a real CustomAttribute-table read (ECMA-335 #~
    # stream: TypeRef -> MemberRef -> CustomAttribute rows) if it ever misfires.
    incompat = [c for c in incompat if b"\x00" + c.encode("utf-8") + b"\x00" not in data]
    return {"guids": guids, "incompat": incompat, "versions": versions}


def _tracked(entry: dict, dirs: tuple[str, ...]) -> list[str]:
    """`entry`'s tracked .dll files (tree-relative, enabled names) under `dirs`."""
    dirs_cf = tuple(d.casefold() for d in dirs)
    return [f for f in entry.get("files", ())
            if f.casefold().endswith(".dll") and f.casefold().startswith(dirs_cf) and ".." not in f.split("/")]


def _on_disk(root: Path, rel: str) -> Path | None:
    """The file under its own name, else its .disabled twin (a switched-off
    / inactive mod's files are renamed), else None."""
    path = root.joinpath(*rel.split("/"))
    for p in (path, path.with_name(path.name + bx.DISABLED_SUFFIX)):
        if p.is_file():
            return p
    return None


def scan_key(entry: dict) -> tuple:
    """What a scan depends on: a Reinstall / Update changes installed_at."""
    return entry["full_name"], entry.get("version"), entry.get("installed_at")


def scan_package(root, entry: dict) -> dict:
    """extract_plugin_info over every tracked plugin DLL of `entry` in the
    tree at `root`, united: {"guids", "incompat", "versions", "skipped"}
    ("skipped" = files missing, unreadable or over BLOB_MAX). Never raises."""
    out = {"guids": [], "incompat": [], "versions": {}, "skipped": 0}
    for rel in _tracked(entry, TREE_DIRS):
        try:
            path = _on_disk(Path(root), rel)
            if path is None or path.stat().st_size > BLOB_MAX:
                out["skipped"] += 1
                continue
            info = extract_plugin_info(path.read_bytes())
        except OSError:
            out["skipped"] += 1
            continue
        for k in ("guids", "incompat"):
            out[k] += [g for g in info[k] if g not in out[k]]
        out["versions"] = {**info["versions"], **out["versions"]}  # the first DLL's version of a GUID wins
    return out


def _enabled(manifest: dict, toggles: dict | None) -> list[dict]:
    """Active entries switched on (`toggles` overriding the manifest's
    flags); toggles None = every installed mod, Active and Inactive (the
    screen's worker: its live toggles are applied later, profile_issues)."""
    if toggles is None:
        return manifest["active"] + manifest["inactive"]
    return [e for e in manifest["active"] if toggles.get(e["full_name"], e.get("enabled", True))]


def file_conflicts(root, manifest: dict, toggles: dict | None) -> list[dict]:
    """[{"a", "b", "files": [basename, ...]}] per package pair (manifest
    order) whose .dll files under CODE_DIRS share a name (case-folded; the
    path differs per package folder) and differ in content. Only shared
    names are read: size first, sha1 when the sizes match. Never raises."""
    root = Path(root)
    by_name: dict[str, dict[str, str]] = {}  # basename -> {full_name: rel}
    for e in _enabled(manifest, toggles):
        for rel in _tracked(e, CODE_DIRS):
            by_name.setdefault(rel.rsplit("/", 1)[-1].casefold(), {}).setdefault(e["full_name"], rel)
    sizes: dict[str, int | None] = {}
    digests: dict[str, str | None] = {}

    def size(rel: str) -> int | None:  # None = missing / unreadable / over BLOB_MAX
        if rel not in sizes:
            try:
                path = _on_disk(root, rel)
                sizes[rel] = path.stat().st_size if path is not None else None
            except OSError:
                sizes[rel] = None
            if sizes[rel] is not None and sizes[rel] > BLOB_MAX:
                sizes[rel] = None
        return sizes[rel]

    def digest(rel: str) -> str | None:
        if rel not in digests:
            try:
                digests[rel] = hashlib.sha1(_on_disk(root, rel).read_bytes()).hexdigest()
            except (OSError, AttributeError):  # AttributeError: gone since size()
                digests[rel] = None
        return digests[rel]

    pairs: dict[tuple[str, str], list[str]] = {}
    for owners in by_name.values():
        names = list(owners)
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                ra, rb = owners[a], owners[b]
                sa, sb = size(ra), size(rb)
                if sa is None or sb is None:  # a file we can't read: no claim either way
                    continue
                if sa == sb and (digest(ra) is None or digest(rb) is None or digest(ra) == digest(rb)):
                    continue
                pairs.setdefault((a, b), []).append(ra.rsplit("/", 1)[-1])
    return [{"a": a, "b": b, "files": files} for (a, b), files in pairs.items()]


def _owners(enabled: list[str], scans: dict[str, dict]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n in enabled:
        for g in (scans.get(n) or {}).get("guids", ()):
            out.setdefault(g, []).append(n)
    return out


def plugin_duplicates(enabled: list[str], scans: dict[str, dict]) -> list[dict]:
    """[{"a", "b", "guid"}]: two of the `enabled` packages (in order) carry a
    plugin with the same GUID. `scans`: full_name -> scan_package result."""
    out = []
    for guid, owners in _owners(enabled, scans).items():
        for i, a in enumerate(owners):
            out += [{"a": a, "b": b, "guid": guid} for b in owners[i + 1:]]
    return out


def declared_incompatibilities(enabled: list[str], scans: dict[str, dict]) -> list[dict]:
    """[{"dropped", "blocker", "guid"}]: an `enabled` package declares a GUID
    incompatible that another enabled package's plugin has - BepInEx drops
    the declarer, the blocker loads."""
    owners = _owners(enabled, scans)
    out = []
    for p in enabled:
        for g in (scans.get(p) or {}).get("incompat", ()):
            out += [{"dropped": p, "blocker": q, "guid": g} for q in owners.get(g, ()) if q != p]
    return out


def required_by(entries: dict[str, dict], full_name: str, framework: str | None = None) -> list[str]:
    """The installed mods (Active and Inactive; the framework left out) that
    declare `full_name` a dependency, in `entries` order (the caller sorts)."""
    return [n for n, e in entries.items()
            if n != framework and n != full_name and full_name in _declared_dependencies(e)]


def _vkey(version) -> tuple:
    """"1.0.9" -> (1, 0, 9); the leading digits-and-dots only; () = unknown."""
    m = re.match(r"[\d.]*", version) if isinstance(version, str) else None
    return tuple(int(x) for x in m.group().split(".") if x) if m else ()


def _keep(a: tuple, b: tuple) -> tuple[str | None, str | None]:
    """Which of two versions of one mod to keep: (full_name, why). Each side
    is (full_name, switched-on dependents, package version, plugin version).
    The one the other mods need ("needed"), else the newer one ("newer":
    package version, then plugin version), else (None, None)."""
    if bool(a[1]) != bool(b[1]):
        return (a if a[1] else b)[0], "needed"
    for i in (2, 3):
        ka, kb = _vkey(a[i]), _vkey(b[i])
        if ka and kb and ka != kb:
            return (a if ka > kb else b)[0], "newer"
    return None, None


def _name(entries: dict[str, dict], full_name: str) -> str:
    e = entries.get(full_name)
    return (e.get("display_name") or e.get("name") or full_name) if e else full_name


def profile_issues(entries: dict[str, dict], active_ids: list[str], toggles: dict[str, bool],
                   scans: dict[str, dict], file_hits: list[dict], framework: str | None = None) -> list[dict]:
    """The four kinds (module docstring) for the Active, switched-on mods of
    `active_ids` (on-screen order, framework left out) as issue dicts:
    dependency_issues' {"mod_id", "dep", "kind", "severity", "text"} plus
    "dep_name" (the other mod as on screen), "needed_by" (display names of
    the mods that need mod_id, sorted) and per kind "guid" (incompatible,
    duplicate_plugin) or "files"
    (duplicate_file); two_versions carries "guid", "files", "version" /
    "dep_version", "plugin_version" / "dep_plugin_version", "keep" /
    "keep_why" (_keep) and switched-on dependents only, both sides:
    "needed_by" / "dep_needed_by". One issue per pair, listed under the later mod in
    Active order (incompatible: under the dropped one). `scans`: full_name
    -> scan_package result (missing = not scanned yet); `file_hits`:
    file_conflicts' result (pairs not both enabled are ignored). Logs one
    line per call and one per issue. Never raises."""
    try:
        t0 = time.monotonic()
        enabled = [n for n in active_ids if n in entries and toggles.get(n, True)]
        pos = {n: i for i, n in enumerate(enabled)}
        found: list[tuple[str, str, str, dict]] = []  # (kind, mod_id, dep, extras)

        def later(a: str, b: str) -> tuple[str, str]:
            return (a, b) if pos[a] > pos[b] else (b, a)

        for d in declared_incompatibilities(enabled, scans):
            found.append(("incompatible", d["dropped"], d["blocker"], {"guid": d["guid"]}))
        files_of = {frozenset((h["a"], h["b"])): h["files"] for h in file_hits if h["a"] in pos and h["b"] in pos}
        on = set(enabled)

        def side(n: str, guid: str) -> tuple:
            needers = sorted((_name(entries, m) for m in required_by(entries, n, framework) if m in on), key=str.casefold)
            return n, needers, entries[n].get("version"), ((scans.get(n) or {}).get("versions") or {}).get(guid)

        for d in plugin_duplicates(enabled, scans):
            mod_id, dep = later(d["a"], d["b"])
            found.append(("duplicate_plugin", mod_id, dep, {"guid": d["guid"]}))
            files = files_of.get(frozenset((mod_id, dep)))
            if files and dep not in _declared_dependencies(entries[mod_id]) \
                    and mod_id not in _declared_dependencies(entries[dep]):
                a, b = side(mod_id, d["guid"]), side(dep, d["guid"])
                keep, why = _keep(a, b)
                found.append(("two_versions", mod_id, dep, {
                    "guid": d["guid"], "files": list(files), "needed_by": a[1], "dep_needed_by": b[1],
                    "version": a[2], "dep_version": b[2], "plugin_version": a[3], "dep_plugin_version": b[3],
                    "keep": keep, "keep_why": why}))
        for pair, files in files_of.items():
            found.append(("duplicate_file", *later(*pair), {"files": list(files)}))
        found.sort(key=lambda f: KIND_RANK.index(f[0]))  # stable: the strongest kind of a pair comes first
        seen: set[frozenset] = set()
        out: list[dict] = []
        for kind, mod_id, dep, extras in found:
            pair = frozenset((mod_id, dep))
            if pair in seen:
                continue
            seen.add(pair)
            dep_name = _name(entries, dep)
            out.append({"mod_id": mod_id, "dep": dep, "kind": kind,
                        "severity": "error" if kind == "two_versions" and pair in HARD_CLASH_PAIRS else SEVERITY[kind],
                        "text": TEXT[kind].format(dep=dep_name), "dep_name": dep_name,
                        "needed_by": sorted((_name(entries, n) for n in required_by(entries, mod_id, framework)),
                                            key=str.casefold),
                        **extras})
        out.sort(key=lambda i: pos[i["mod_id"]])
        counts = {k: sum(1 for i in out if i["kind"] == k) for k in KIND_RANK}
        log(f"[conflicts] {len(enabled)} switched-on mods, {len(scans)} scanned: "
            + ", ".join(f"{k} {n}" for k, n in counts.items()) + f" ({(time.monotonic() - t0) * 1000:.0f} ms)")
        for i in out:
            log(f"[conflicts] {i['kind']} ({i['severity']}): {i['mod_id']} / {i['dep']}"
                + (f" {clip(i.get('files') or i.get('guid'), 300)}"))
        return out
    except Exception as err:  # a check that can't run must never break the screen
        log(f"[conflicts] check failed ({err!r}); no conflict issues")
        return []
