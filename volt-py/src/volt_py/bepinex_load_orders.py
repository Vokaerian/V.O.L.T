"""Load orders for Thunderstore/BepInEx games (THUNDERSTORE.md §2): each one
is a complete, independent BepInEx tree under that game's APP-ROOT -
<APP-ROOT>/load-orders/<slug>/ holds loadorder.json (the manifest) beside the
tree itself (BepInEx/{core,plugins,config,patchers,monomod}, winhttp.dll,
doorstop_config.ini, ...). Never inside the real game install. Deliberately
NOT load_orders.py (RimWorld's): that manifest references mods in a shared
Mods folder; here the load order IS the tree, so the manifest tracks what is
installed in it and which files each package put where.

Same folder name (load-orders/), file name (loadorder.json), slug rules and
JSON conventions (snake_case, schema_version, ISO created_at/updated_at) as
RimWorld's - only the shape inside differs.

Manifest (schema_version 1):
{
  "schema_version": 1,
  "name": "Vanilla+",                       # display name; folder name is the slug
  "created_at": "<ISO>", "updated_at": "<ISO>",
  "framework": <entry>,                     # the game's BepInExPack, installed at
                                            #   create; pinned, never in active/inactive
  "active":   [<entry>, ...],               # ordered (cosmetic for BepInEx, kept for
                                            #   the UI); each has its own "enabled"
  "inactive": [<entry>, ...]                # still installed, files disabled on disk
}
<entry> = {
  "full_name": "ValheimModding-Jotunn", "namespace": "ValheimModding", "name": "Jotunn",
  "version": "2.30.0", "display_name": "Jotunn", "description": "...", "website_url": "...",
  "dependencies": ["denikson-BepInExPack_Valheim-5.4.2333", ...],  # as declared (install_mod resolves the versions)
  "enabled": true,               # active-list toggle; always true for framework/inactive-irrelevant
  "online_source": true,         # false = imported from a local zip (THUNDERSTORE.md §8b):
                                 #   never update-checked; absent in older manifests = true
  "installed_at": "<ISO>",
  "files": ["BepInEx/plugins/ValheimModding-Jotunn/Jotunn.dll", ...],  # tree-relative, enabled names
  "config_sha256": {"BepInEx/config/x.cfg": "<sha256>"},  # 0.6.50, optional: the config files it wrote (a record)
  "skipped_dependencies": ["bbepis-BepInExPack"]  # 0.6.51, optional: listed dependencies install_mod left
}                                # out as another game's (dependency_issues never calls them missing)
On disk, a mod's files are enabled (plain names) iff it is in `active` with
enabled=true; `inactive` mods and toggled-off active mods are renamed with
bepinex_install.DISABLED_SUFFIX. save_load_order() is the one place that
materializes this. Unknown top-level fields are preserved.

Network goes through thunderstore.py (fetch_package / ensure_cached), so the
check harness fakes thunderstore.env.urlopen. Dependency auto-install
(THUNDERSTORE.md §1): install_mod() pulls in every declared dependency not yet
installed, recursively. Since 0.6.50 at the EXACT version the dependency
string names (Gale's rule: breadth first, the first version seen of a
package wins, a version that's gone falls back to the latest, recorded);
before, every dependency was taken at its latest, which pulled a modpack's
mods past the versions it was built with (Lethal_Enhanced_Party_Edition:
34 newer, TeamXiaolan-DawnLibExperimental next to DawnLib). Dependencies are
extracted first, the target last. A dependency that can't be
fetched/installed is reported as a problem, not a failure of the whole
install; the requested package failing raises. Config files: every
install overwrites the config files the package ships (0.6.51, Gale's rule,
bepinex_install.install_package). 0.6.51: the community index
(thunderstore_index) answers the exact-version lookups with no request, and
a dependency from another game's community is left out (Gale's rule).

Updates (THUNDERSTORE.md §3, stage 3b): check_updates() finds every
installed package's current latest version (online_source ones only) - from
the community index since 0.6.52 (rebuilt when over an hour old), per package
only for what it lacks or when it can't be built - and update_mod() re-downloads + installs one package (the framework
included) in place - new files overwrite, files the old version had and the
new one doesn't are deleted, the config files it ships overwritten (0.6.51;
others kept), the mod's on-disk enabled/disabled state preserved. The manager screen runs both off the GUI thread.

Import/Export (THUNDERSTORE.md §4, stage 3e) lives in bepinex_share.py and
builds on this module's two pinning hooks: create_load_order(framework_
version=) and install_mod(pins=, fallback_latest=) reproduce a profile's
exact versions, falling back to Thunderstore's latest (and saying so) for a
version that's gone.

Import local mod (THUNDERSTORE.md §8b): inspect_local_package() validates a
locally picked Thunderstore-shaped zip (the dialog's preview) and
import_local_mod() installs it - the zip copied into the shared package
cache under its Team-Package-Version key, then install_mod()'s own path
(already-installed / framework guard, routing, append to Active, missing
dependencies from Thunderstore), the entry recorded online_source: false.

Clean cache (THUNDERSTORE.md §8c): clean_package_cache() deletes every
cached package zip no load order references (framework, active or
inactive); the pure unreferenced_cache_files() decides which. An unreadable
manifest aborts it with nothing deleted.

Download progress (0.6.25, PLAN.md §11 (a)): inside `with
package_progress(cb):` every package fetch + install (_fetch_and_install -
create_load_order's framework, install_mod and its dependencies, update_mod,
an import's mods) calls cb({"type": "start", "id": full_name})
before it and cb({"type": "item-done", "id", "ok", "message"}) after it (a
cache hit = start + done at once). The manager screen's footer bar folds
these into download_state (apply_package_event); the existing text
progress (`report` / `progress=`) is untouched.

Total up front (0.6.26, PLAN.md §11 (d)): plan_downloads() is a pre-pass a
download job runs before its installs - the mods the install will fetch
(targets not yet installed + their missing required mods, resolved as
install_mod does, through thunderstore_browse.dependency_chain), announced
as one {"type": "plan", "ids": [...]} event, so the bar's total is known
before the first download. Inside package_progress every package metadata
lookup is remembered for the rest of the block (_fetch_meta; since 0.6.50
also each pinned version's list), so the install reuses the pre-pass's
requests instead of repeating them; since 0.6.50 its lookups run
FETCH_WORKERS at a time (one at a time before: ~100 s for a 300-mod
modpack) and it has no cap (was thunderstore_browse.CHAIN_LIMIT). The
pre-pass never raises and never changes what the install does; a mod it
missed still joins the total when it starts, as before. Since 0.6.34 it
first emits {"type": "checking"} (the bar reads "Checking required
mods..."), and every way out of it emits a "plan" (an empty one on a
failure) that ends that state; a job that fails or ends meanwhile hides the
bar as always. Since 0.6.51 it first makes sure the community index is
fresh (thunderstore_index.ensure); while that downloads (~12 s, once a day)
it emits {"type": "indexing"} (the bar reads "Updating package list..."),
then "checking" again; with the index warm the walk makes no request for
a version the index has (~1 s for a 300-mod modpack).

Missing files (0.6.27, PLAN.md §11 (f)): the manifest is the truth for what is
installed (THUNDERSTORE.md §3a), so files deleted from a tree outside VOLT
(Explorer, an antivirus quarantine) went unnoticed. missing_files() compares
each installed mod's tracked non-config files with the tree - one walk of
BepInEx/, a file counting as present under its own name or its
DISABLED_SUFFIX twin; config files and the framework are left out - and
files_issue() turns a result into the manager's "files" issue.
reinstall_mod() is the fix: update_mod(reinstall=True) at the installed
version, from the cached zip (downloaded first when it's gone), keeping the
mod's on-disk state and list position (its own config files are written
again, 0.6.51).
"""

import os
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import bepinex_install as bx
from . import thunderstore as ts
from . import thunderstore_browse as tb
from . import thunderstore_index as pi
from .applog import clip, log
from .fsutil import read_json, remove_tree_best_effort, write_json
from .mods import natural_key
from .slug import is_valid_slug, slugify

DIR_NAME = "load-orders"
MANIFEST_FILE = "loadorder.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ThunderstoreGame:
    """The per-game facts this module needs (THUNDERSTORE.md's per-game
    checklist): APP-ROOT slug, Thunderstore community slug (URLs in the mod
    browser), and the one canonical framework package's full_name."""

    slug: str
    community: str
    framework_package: str

    @property
    def framework_ref(self) -> ts.PackageRef:
        return ts.PackageRef.parse(self.framework_package)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_orders_root(app_root) -> Path:
    return Path(app_root) / DIR_NAME


def assert_slug(slug) -> None:
    # The one guard between a slug and filesystem traversal - keep it strict.
    if not is_valid_slug(slug):
        raise ValueError(f"Invalid load order id: {slug!r}")


def tree_root(app_root, slug) -> Path:
    """The load order's folder = the root its BepInEx tree hangs off."""
    assert_slug(slug)
    return load_orders_root(app_root) / slug


def bepinex_dir(app_root, slug) -> Path:
    return tree_root(app_root, slug) / bx.BEPINEX_DIR


def manifest_path(app_root, slug) -> Path:
    return tree_root(app_root, slug) / MANIFEST_FILE


def _entry(raw) -> dict | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("full_name"), str):
        return None
    try:
        ref = ts.PackageRef.parse(raw["full_name"])
    except ValueError:
        return None
    files = raw.get("files")
    deps = raw.get("dependencies")
    return {
        **raw,
        "full_name": ref.full_name,
        "namespace": ref.namespace,
        "name": ref.name,
        "version": raw.get("version") if isinstance(raw.get("version"), str) else "",
        "display_name": raw.get("display_name") if isinstance(raw.get("display_name"), str) and raw["display_name"] else ref.name,
        "description": raw.get("description") if isinstance(raw.get("description"), str) else "",
        "website_url": raw.get("website_url") if isinstance(raw.get("website_url"), str) else "",
        "dependencies": [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else [],
        "enabled": raw.get("enabled") is not False,
        "online_source": raw.get("online_source") is not False,
        "installed_at": raw.get("installed_at"),
        "files": [f for f in files if isinstance(f, str)] if isinstance(files, list) else [],
    }


def _entries(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out, seen = [], set()
    for r in raw:
        e = _entry(r)
        if e and e["full_name"] not in seen:
            seen.add(e["full_name"])
            out.append(e)
    return out


def normalize_manifest(raw, slug: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("manifest is not a JSON object")
    ver = raw.get("schema_version")
    if isinstance(ver, (int, float)) and not isinstance(ver, bool) and ver > SCHEMA_VERSION:
        raise ValueError(f"manifest schema_version {ver} is newer than this app supports ({SCHEMA_VERSION})")
    name = raw.get("name")
    framework = _entry(raw.get("framework"))
    if framework:
        framework["enabled"] = True
    active = _entries(raw.get("active"))
    taken = {e["full_name"] for e in active} | ({framework["full_name"]} if framework else set())
    inactive = [e for e in _entries(raw.get("inactive")) if e["full_name"] not in taken]
    return {
        **raw,
        "slug": slug,
        "schema_version": SCHEMA_VERSION,
        "name": name if isinstance(name, str) and name.strip() else slug,
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "framework": framework,
        "active": active,
        "inactive": inactive,
    }


def installed(manifest: dict) -> dict[str, dict]:
    """full_name -> entry for everything installed in the tree (framework
    included), active first."""
    out = {}
    if manifest.get("framework"):
        out[manifest["framework"]["full_name"]] = manifest["framework"]
    for e in manifest["active"] + manifest["inactive"]:
        out[e["full_name"]] = e
    return out


# ---- dependency presence (THUNDERSTORE.md §3): the manager's "⚠ N · ✕ M" issues ----
ISSUE_TEXT = {
    "missing": "requires {dep}, which isn't installed",
    "inactive": "requires {dep}, which is inactive",
    "off": "requires {dep}, which is switched off",
}


def _declared_dependencies(entry: dict | None) -> list[str]:
    """The full_names an installed entry declares (bad strings skipped, each
    once), minus those its install left out as another game's (0.6.51,
    "skipped_dependencies": never "missing", Install missing never asks for them)."""
    out: list[str] = []
    left_out = (entry or {}).get("skipped_dependencies")
    left_out = set(left_out) if isinstance(left_out, list) else set()
    for dep in (entry or {}).get("dependencies", ()):
        try:
            name = ts.PackageRef.parse(dep).full_name
        except ValueError:
            continue
        if name not in out and name not in left_out:
            out.append(name)
    return out


def dependency_issues(entries: dict[str, dict], active_ids: list[str], toggles: dict[str, bool],
                      framework_package: str | None) -> list[dict]:
    """The manager's dependency issues: for each Active, switched-on mod,
    each declared dependency (the game's framework package aside - it's
    part of every load order, never a listed dependency) that isn't
    installed (kind "missing", severity "error"), is installed but not in
    Active ("inactive", "warning") or is in Active but switched off ("off",
    "warning"). One dict per (mod, dependency): {"mod_id", "dep", "kind",
    "severity", "text"} in Active order. Qt-free; the screen derives its
    per-row lists and the "⚠ N · ✕ M" count from this."""
    active = set(active_ids)
    out: list[dict] = []
    for mod_id in active_ids:
        if not toggles.get(mod_id, True):
            continue
        for dep in _declared_dependencies(entries.get(mod_id)):
            if dep == framework_package or dep == mod_id:
                continue
            if dep not in entries:
                kind, severity = "missing", "error"
            elif dep not in active:
                kind, severity = "inactive", "warning"
            elif not toggles.get(dep, True):
                kind, severity = "off", "warning"
            else:
                continue
            out.append({"mod_id": mod_id, "dep": dep, "kind": kind, "severity": severity,
                        "text": ISSUE_TEXT[kind].format(dep=dep)})
    return out


def missing_packages(issues: list[dict], mod_id: str | None = None) -> list[str]:
    """The packages the "missing" issues ask for (each once, issue order) -
    what "Install all missing" installs; for `mod_id`, just that mod's."""
    out: list[str] = []
    for issue in issues:
        if issue["kind"] == "missing" and (mod_id is None or issue["mod_id"] == mod_id) and issue["dep"] not in out:
            out.append(issue["dep"])
    return out


def mod_missing_dependencies(entries: dict[str, dict], mod_id: str, framework_package: str | None) -> list[str]:
    """A mod's declared dependencies that aren't installed, whatever list it
    sits in (the row menu's "Install missing dependencies" - an inactive
    mod has no issue lines but can still be fixed up)."""
    return [dep for dep in _declared_dependencies(entries.get(mod_id))
            if dep != framework_package and dep != mod_id and dep not in entries]


# ---- missing files (0.6.27; module docstring, "Missing files") ----
FILES_ISSUE_TEXT = ("Some of this mod's files are gone from the profile folder (deleted outside VOLT?). "
                    "Right-click > Reinstall to fix it.")
FILES_ISSUE_TEXT_ALL = ("All of this mod's files are gone from the profile folder (deleted outside VOLT?). "
                        "Right-click > Reinstall to fix it.")


def missing_files(app_root, slug, manifest: dict) -> dict[str, tuple[int, int]]:
    """{full_name: (missing, total)} for each installed mod (Active and
    Inactive; the framework left out) with at least one tracked non-config
    file missing from the tree under both its own name and its disabled
    twin - total = its tracked non-config files; healthy mods aren't listed.
    One os.walk of <tree>/BepInEx (every non-framework file routes under it,
    bepinex_install.route_file) instead of a stat per file; names compared
    case-folded (Windows' file system ignores case). One log line per call.
    Never raises: any failure is logged and gives {}."""
    try:
        t0 = time.monotonic()
        root = tree_root(app_root, slug)
        present: set[str] = set()
        for dirpath, _dirs, files in os.walk(root / bx.BEPINEX_DIR):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            present.update(f"{rel_dir}/{f}".casefold() for f in files)
        out: dict[str, tuple[int, int]] = {}
        for e in manifest["active"] + manifest["inactive"]:
            tracked = [f for f in e["files"] if not bx.is_config_path(f)]
            gone = sum(1 for f in tracked
                       if f.casefold() not in present and (f + bx.DISABLED_SUFFIX).casefold() not in present)
            if gone:
                out[e["full_name"]] = (gone, len(tracked))
        mods = len(manifest["active"]) + len(manifest["inactive"])
        detail = ", ".join(f"{n} ({m}/{t}{' ALL' if m == t else ''})" for n, (m, t) in out.items())
        log(f"[loadorders] {slug}: files check: {len(out)} of {mods} mods have files missing"
            f" ({len(present)} files in BepInEx/, {(time.monotonic() - t0) * 1000:.0f} ms)"
            + (f": {clip(detail, 1000)}" if out else ""))
        return out
    except Exception as err:  # a check that can't run must never stop the profile from opening
        log(f"[loadorders] {slug}: files check failed ({err!r}); no mod marked")
        return {}


def files_issue(mod_id: str, missing: int, total: int) -> dict:
    """missing_files' result for one mod as a manager issue (the
    dependency_issues shape, kind "files", severity "warning"; "dep" = the
    mod itself, so (mod_id, dep) stays a unique key)."""
    return {"mod_id": mod_id, "dep": mod_id, "kind": "files", "severity": "warning",
            "missing": missing, "total": total,
            "text": FILES_ISSUE_TEXT_ALL if missing >= total else FILES_ISSUE_TEXT}


def reinstall_source(app_root, entry: dict) -> str | None:
    """Where reinstall_mod would get `entry`'s zip: "cache" (its exact
    version is in the package cache), "download" (from Thunderstore), or
    None (a local .zip mod whose cached copy is gone: nowhere to get it)."""
    try:
        ref = ts.PackageRef(entry["namespace"], entry["name"], entry["version"])
    except ValueError:
        return None
    if ts.cached_package(app_root, ref) is not None:
        return "cache"
    return "download" if entry.get("online_source", True) else None


def _write(app_root, slug, manifest: dict) -> dict:
    manifest = {k: v for k, v in manifest.items() if k != "slug"}
    manifest["schema_version"] = SCHEMA_VERSION
    manifest["updated_at"] = _now()
    write_json(manifest_path(app_root, slug), manifest)
    return normalize_manifest(manifest, slug)


def list_load_orders(app_root) -> list[dict]:
    """One row per load order folder (natural name order): {slug, name,
    updated_at, active_count, framework_version} - or {slug, name, error} for
    a folder whose manifest can't be read, so one bad one never hides the rest."""
    try:
        entries = list(os.scandir(load_orders_root(app_root)))
    except FileNotFoundError:
        return []
    out = []
    for e in entries:
        if not e.is_dir() or not is_valid_slug(e.name):
            continue
        try:
            m = normalize_manifest(read_json(manifest_path(app_root, e.name)), e.name)
            out.append({
                "slug": e.name, "name": m["name"], "updated_at": m["updated_at"],
                "active_count": len(m["active"]),
                "framework_version": m["framework"]["version"] if m["framework"] else None,
            })
        except Exception as err:
            out.append({"slug": e.name, "name": e.name, "error": str(err)})
    return sorted(out, key=lambda o: (natural_key(o["name"]), o["slug"]))  # slug breaks a name tie


def load_load_order(app_root, slug) -> dict:
    return normalize_manifest(read_json(manifest_path(app_root, slug)), slug)


def _allocate(app_root, name) -> tuple[str, str]:
    """(display name, fresh slug): slug the name, suffix -2, -3... on collision,
    the folder created (non-recursive mkdir, so a race can't reuse one)."""
    display = ("" if name is None else str(name)).strip()
    if not display:
        raise ValueError("Profile name is empty")
    root = load_orders_root(app_root)
    root.mkdir(parents=True, exist_ok=True)
    base = slugify(display)
    for n in range(1, 1000):
        slug = base if n == 1 else f"{base}-{n}"
        try:
            (root / slug).mkdir()
        except FileExistsError:
            continue
        return display, slug
    raise ValueError(f'Too many profiles named like "{display}"')


def _make_entry(ref: ts.PackageRef, result: dict) -> dict:
    m = result["manifest"]
    return {
        "full_name": ref.full_name, "namespace": ref.namespace, "name": ref.name,
        "version": m["version_number"], "display_name": m["name"],
        "description": m["description"], "website_url": m["website_url"],
        "dependencies": list(m["dependencies"]),
        "enabled": True, "online_source": True, "installed_at": _now(),
        "files": list(result["files"]),
        "config_sha256": dict(result.get("config_sha256") or {}),  # 0.6.50: what it wrote (a record only since 0.6.51)
    }


# ponytail: a per-thread hook instead of a progress= parameter threaded through
# create_load_order / install_mod / update_mod / bepinex_share's imports; each
# screen job is its own thread, so jobs never see each other's hook. Make it a
# parameter if a caller ever needs progress across threads.
_progress = threading.local()


@contextmanager
def package_progress(cb):
    """Within the block (on this thread), every package fetch + install
    reports to cb(event) - module docstring, "Download progress"."""
    prev = getattr(_progress, "cb", None), getattr(_progress, "meta", None)
    _progress.cb, _progress.meta = cb, {}  # meta: _fetch_meta's lookups, for this block only
    try:
        yield
    finally:
        _progress.cb, _progress.meta = prev


def _fetch_meta(namespace: str, name: str, app_version=None) -> dict:
    """ts.fetch_package, remembered for the rest of a package_progress block
    (the pre-pass's lookups serve the install); a plain fetch outside one.
    Failures aren't remembered (the install asks again, as it always did)."""
    memo = getattr(_progress, "meta", None)
    key = f"{namespace}-{name}"
    if memo is not None and key in memo:
        return memo[key]
    meta = ts.fetch_package(namespace, name, app_version)
    if memo is not None:
        memo[key] = meta
    return meta


def _zip_dependencies(app_root, ref: ts.PackageRef) -> list[str] | None:
    """A pinned version's dependency strings from its cached zip's
    manifest.json (no request); None when it isn't cached or can't be read."""
    path = ts.cached_package(app_root, ref) if ref.version is not None else None
    if path is None:
        return None
    try:
        with bx.PackageSource(path) as src:
            return list(bx.read_manifest(src)["dependencies"])
    except (bx.PackageError, OSError) as err:
        log(f"[loadorders] {ref.key}: cached zip unreadable for its dependencies ({err})")
        return None


def _known_dependencies(memo: dict, ref: ts.PackageRef) -> list[str] | None:
    """A pinned version's dependency strings when an earlier lookup of this
    block (the pre-pass) already has them - no request; else None."""
    if ref.key in memo:
        return memo[ref.key]
    latest = (memo.get(ref.full_name) or {}).get("latest") or {}
    if latest.get("version_number") == ref.version:
        return [d for d in latest.get("dependencies") or [] if isinstance(d, str)]
    return None


def plan_downloads(app_root, slug, game: ThunderstoreGame, refs, app_version=None, *, lookup_pinned: bool = True) -> list[str]:
    """The pre-pass (module docstring, "Total up front"): inside
    package_progress, the full_names installing `refs` into load order
    `slug` (None = a load order not created yet: only the framework counts
    as there) will fetch - each ref not installed yet, then their missing
    required mods (install_mod's walk: thunderstore_browse.dependency_chain
    at the exact versions, first seen wins; no cap since 0.6.50), looked up
    FETCH_WORKERS at a time (0.6.50; one at a time before) - emitted as one
    "plan" event and returned. A pinned version's list comes from its cached
    zip, else Thunderstore (version_dependencies); `lookup_pinned` False (an
    import: every listed mod pinned) keeps a pinned ref without a cached zip
    from costing a request (its own dependencies then aren't counted).
    0.6.51: the community index first (thunderstore_index.ensure - built
    here when missing or stale, the bar reading "Updating package list..."
    meanwhile; any failure = the per-package lookups as before); a
    dependency (not one of `refs`) the index lacks is checked against the
    game's community - another game's is left out (Gale's rule), never
    counted. Outside package_progress: nothing, []. Never raises."""
    if getattr(_progress, "cb", None) is None:
        return []
    _emit({"type": "checking"})  # 0.6.34: the bar reads "Checking required mods..." until the "plan" below
    try:
        refs = list(refs)
        have = set(installed(load_load_order(app_root, slug))) if slug else set()
        have.add(game.framework_package)
        memo = _progress.meta  # captured here: the lookups run on worker threads (_progress is per thread)
        built = []
        index = pi.ensure(app_root, game.community, app_version,
                          on_build=lambda: (built.append(1), _emit({"type": "indexing"})))  # "Updating package list..."
        if built:
            _emit({"type": "checking"})  # back to "Checking required mods..."
        targets = {r.full_name for r in refs}

        def lookup(ref: ts.PackageRef):
            hit = index.lookup(ref) if index is not None else None
            if hit is not None:  # in the index = this game's package
                return hit[0], hit[1], False
            community = None if ref.full_name in targets else game.community  # another game's: left out
            if ref.version is not None:
                deps = _zip_dependencies(app_root, ref)
                if deps is None and not lookup_pinned:
                    deps = []  # an import: no request for a pinned mod (its own list then isn't counted)
                if deps is not None:
                    if community and (lookup_pinned or index is not None):
                        _check_community(ref, app_version, memo, community)
                    return ref.version, deps, False
            return tb.version_dependencies(ref, app_version, cache=memo, community=community)

        plan = list(dict.fromkeys(r.full_name for r in refs if r.full_name not in have))
        chain = tb.parallel_dependency_chain([r.key if r.version else r.full_name for r in refs], have,
                                             game.framework_package, app_version, lookup=lookup, limit=None)
        plan += [f for f in chain["missing"] if f not in plan]
    except Exception as err:  # the bar's total must never break an install
        log(f"[loadorders] pre-pass failed ({err!r}); the total grows as mods start")
        _emit({"type": "plan", "ids": []})  # ends "checking" (0.6.34): nothing added, the bar back to normal
        return []
    log(f"[loadorders] pre-pass: {len(plan)} mods to fetch {plan}")
    _emit({"type": "plan", "ids": plan})
    return plan


def _emit(event: dict) -> None:
    cb = getattr(_progress, "cb", None)
    if cb is not None:
        cb(event)


def _fetch_and_install(app_root, slug, ref: ts.PackageRef, framework: bool, app_version=None) -> dict:
    """Resolve `ref` (a pinned version, else Thunderstore's latest), get the
    zip into the shared cache, extract it into the tree. Returns the entry.
    Reports start / item-done to package_progress's hook, if one is set."""
    _emit({"type": "start", "id": ref.full_name})
    try:
        entry = _fetch_and_install_quiet(app_root, slug, ref, framework, app_version)
    except Exception as err:
        _emit({"type": "item-done", "id": ref.full_name, "ok": False, "message": str(err) or repr(err)})
        raise
    _emit({"type": "item-done", "id": ref.full_name, "ok": True})
    return entry


def _download(app_root, ref: ts.PackageRef, app_version=None) -> tuple[ts.PackageRef, Path]:
    """(the versioned ref, its cached zip): a pinned version as is, else
    Thunderstore's latest (one metadata lookup, remembered in a block)."""
    url = None
    if ref.version is None:
        meta = _fetch_meta(ref.namespace, ref.name, app_version)
        ref = ts.latest_ref(meta)
        url = meta["latest"].get("download_url") if isinstance(meta["latest"].get("download_url"), str) else None
    return ref, ts.ensure_cached(app_root, ref, url, app_version)


def _extract(app_root, slug, ref: ts.PackageRef, zip_path, framework: bool) -> dict:
    """Extracts a cached zip into the tree (a corrupt one is evicted). The entry."""
    try:
        result = bx.install_package(zip_path, tree_root(app_root, slug), ref.full_name, framework=framework)
    except bx.PackageError as err:
        if err.kind == "bad-zip":  # a corrupt cached download: don't keep serving it
            ts.evict_cached(app_root, ref)
        raise
    return _make_entry(ref, result)


def _fetch_and_install_quiet(app_root, slug, ref: ts.PackageRef, framework: bool, app_version=None) -> dict:
    ref, zip_path = _download(app_root, ref, app_version)
    return _extract(app_root, slug, ref, zip_path, framework)


def _fetch_pinned_or_latest(app_root, slug, ref: ts.PackageRef, framework: bool, app_version=None) -> tuple[dict, bool]:
    """_fetch_and_install for a pinned `ref` (an import's exact version): if
    that version can't be fetched or installed (gone from Thunderstore, a
    bad download), the package's latest is installed instead. Returns
    (entry, fell_back). An unpinned ref is just _fetch_and_install."""
    try:
        return _fetch_and_install(app_root, slug, ref, framework, app_version), False
    except (ts.ThunderstoreError, bx.PackageError) as err:
        if ref.version is None:
            raise
        log(f"[loadorders] {slug}: {ref.key} unavailable ({err}); falling back to the latest {ref.full_name}")
    entry = _fetch_and_install(app_root, slug, ts.PackageRef(ref.namespace, ref.name), framework, app_version)
    return entry, True


def create_load_order(app_root, name: str, game: ThunderstoreGame, app_version=None, *,
                      framework_version: str | None = None) -> dict:
    """New load order: folder + manifest, then the game's framework package
    downloaded (or taken from the cache) and installed into the tree root, so
    it's launch-ready immediately. `framework_version` pins the framework
    (an import reproducing a profile's exact versions, bepinex_share.py) -
    Thunderstore's latest when None, or when that version can't be fetched
    any more (the caller compares the manifest's framework version to tell).
    If the framework install fails the folder is removed again and the
    error propagates."""
    ref = game.framework_ref if framework_version is None else game.framework_ref.with_version(framework_version)  # validates first
    display, slug = _allocate(app_root, name)
    now = _now()
    manifest = {
        "schema_version": SCHEMA_VERSION, "name": display, "created_at": now, "updated_at": now,
        "framework": None, "active": [], "inactive": [],
    }
    write_json(manifest_path(app_root, slug), manifest)
    log(f"[loadorders] created {slug!r} ({display!r}) at {tree_root(app_root, slug)}")
    try:
        manifest["framework"], _ = _fetch_pinned_or_latest(app_root, slug, ref, framework=True, app_version=app_version)
    except Exception:
        remove_tree_best_effort(tree_root(app_root, slug))
        log(f"[loadorders] framework install failed, removed {slug!r}")
        raise
    return _write(app_root, slug, manifest)


OTHER_COMMUNITY = "other-community"  # install_mod's problem kind for a dependency left out as another game's (0.6.51)


def _check_community(r: ts.PackageRef, app_version, memo: dict, community: str) -> None:
    """OtherCommunityError when `r`'s package is another game's (its
    per-package reply, the memo first); a failed lookup is logged and
    treated as unknown, so an offline install from the cache still works."""
    try:
        tb.checked_meta(r, app_version, cache=memo, community=community)
    except tb.OtherCommunityError:
        raise
    except ts.ThunderstoreError as err:
        log(f"[loadorders] {r.full_name}: community not checked ({err}) - kept")


def install_mod(app_root, slug, game: ThunderstoreGame, target, app_version=None, *,
                pins: dict[str, str] | None = None, fallback_latest: bool = False, target_installer=None,
                target_dependencies=None) -> dict:
    """Installs `target` (a PackageRef or "Team-Package[-Version]" string) into
    the load order, appended to the active list enabled, after every
    declared dependency not yet installed (recursively). 0.6.50 (Gale's
    rule, was "latest of everything"): each dependency at the version its
    dependency string names - or the version `pins` names for that
    full_name (an import's file pins every package it lists, bepinex_share.
    py) - resolved breadth first, the first version seen of a package
    winning (thunderstore_browse.dependency_chain); a version that can't be
    fetched any more falls back to the package's latest and is recorded in
    "fallbacks". Already-installed packages (framework included) are left
    alone. The whole set is resolved first (a pinned version's dependency
    list: its cached zip, else what this block's pre-pass looked up, else
    its download - the zip's own manifest.json), then extracted
    dependencies first, the target LAST (so a modpack's config files are the
    last written: every package overwrites the config files it ships, 0.6.51,
    bepinex_install.install_package). 0.6.51: the community index
    (thunderstore_index.current, built by the pre-pass; never the network
    here) answers a pinned version's list first; a dependency it lacks is
    checked against the game's community (the per-package reply, the
    pre-pass's memo first) and another game's is LEFT OUT (Gale's rule):
    a problem of kind "other-community", recorded on each installed entry
    that lists it ("skipped_dependencies") so it never reads as missing.
    The target and the packages `pins` names are never left out (asked for
    by name / listed by the import's file). Returns {"installed": [entries,
    dependencies first], "problems": [{kind, path,
    message, package}], "fallbacks": [{package, wanted, installed}]} - a
    dependency that fails is a problem; the target itself failing raises
    (ThunderstoreError / PackageError). The target's own pinned version is
    exact unless `fallback_latest` (an import): the browser's Versions tab.
    `target_installer(ref) -> entry` replaces the target's
    own fetch + install (import_local_mod: the picked zip instead of a
    download; its `target_dependencies` are the zip's own); dependencies
    still come from Thunderstore."""
    ref = target if isinstance(target, ts.PackageRef) else ts.PackageRef.parse(target)
    manifest = load_load_order(app_root, slug)
    have = installed(manifest)
    if ref.full_name == game.framework_package or ref.full_name in have:
        log(f"[loadorders] {slug}: {ref.full_name} already installed, nothing to do")
        return {"installed": [], "problems": [], "fallbacks": []}
    memo = getattr(_progress, "meta", None)
    memo = {} if memo is None else memo  # the pre-pass's lookups, when this runs inside its block
    resolved: dict[str, tuple] = {}  # full_name -> (ref to install, wanted version, fell back, downloaded already)
    failed: dict[str, Exception] = {}
    announced: set[str] = set()  # got a "start" event during the lookups
    problems, fallbacks, done = [], [], []
    index = pi.current(app_root, game.community)
    exempt = {ref.full_name, *(pins or ())}  # never left out as another game's

    def lookup(r: ts.PackageRef):
        is_target = r.full_name == ref.full_name
        try:
            hit = index.lookup(r) if index is not None else None
            if is_target and target_installer is not None:
                deps = list(target_dependencies or [])
                resolved[r.full_name] = (r, r.version, False, True)
            elif hit is not None:  # in the index = this game's package
                deps = hit[1]
                resolved[r.full_name] = (r, r.version, False, False)
            else:
                if r.full_name not in exempt:
                    _check_community(r, app_version, memo, game.community)  # another game's: OtherCommunityError
                if r.version is None:
                    meta = _fetch_meta(r.namespace, r.name, app_version)
                    latest = ts.latest_ref(meta)
                    deps = [d for d in meta["latest"].get("dependencies") or [] if isinstance(d, str)]
                    resolved[r.full_name] = (latest, None, False, False)
                else:
                    deps = _zip_dependencies(app_root, r)
                    if deps is None:
                        deps = _known_dependencies(memo, r)
                    if deps is not None:
                        resolved[r.full_name] = (r, r.version, False, False)
                    else:  # not known yet: download it now (the install needs the zip anyway); its manifest.json has the list
                        deps = _download_for_dependencies(r, exact=is_target and not fallback_latest)
            for dep in deps:
                try:
                    ts.PackageRef.parse(dep)
                except ValueError as err:
                    problems.append({"kind": "bad-dependency", "path": "", "message": str(err), "package": r.full_name})
            return resolved[r.full_name][0].version, deps, resolved[r.full_name][2]
        except Exception as err:
            failed[r.full_name] = err
            if r.full_name not in announced and not isinstance(err, tb.OtherCommunityError):  # the bar marks it failed
                _emit({"type": "start", "id": r.full_name})
                _emit({"type": "item-done", "id": r.full_name, "ok": False, "message": str(err) or repr(err)})
            raise

    def _download_for_dependencies(r: ts.PackageRef, exact: bool) -> list[str]:
        announced.add(r.full_name)
        _emit({"type": "start", "id": r.full_name})
        try:
            try:
                got, zip_path, fell_back = r, ts.ensure_cached(app_root, r, None, app_version), False
                deps = _zip_dependencies_strict(app_root, got, zip_path)
            except (ts.ThunderstoreError, bx.PackageError) as err:
                if exact:
                    raise
                log(f"[loadorders] {slug}: {r.key} unavailable ({err}); falling back to the latest {r.full_name}")
                got, zip_path = _download(app_root, ts.PackageRef(r.namespace, r.name), app_version)
                deps, fell_back = _zip_dependencies_strict(app_root, got, zip_path), True
        except Exception as err:
            _emit({"type": "item-done", "id": r.full_name, "ok": False, "message": str(err) or repr(err)})
            raise
        _emit({"type": "item-done", "id": r.full_name, "ok": True})
        resolved[r.full_name] = (got, r.version, fell_back, True)
        return deps

    if pins and ref.version is None and pins.get(ref.full_name):
        ref = ref.with_version(pins[ref.full_name])
    chain = tb.dependency_chain([ref.key if ref.version else ref.full_name], have, game.framework_package, app_version,
                                lookup=lookup, limit=None, pins=pins)
    if ref.full_name not in resolved:
        raise failed.get(ref.full_name) or ts.ThunderstoreError(f"Couldn't look up {ref.full_name}.")
    for name, message in chain["problems"]:
        if name in chain["skipped"]:
            problems.append({"kind": OTHER_COMMUNITY, "path": "", "message": message, "package": name})
            log(f"[loadorders] {slug}: dependency {name} left out: {message}")
        elif name in failed:
            err = failed[name]
            problem = err.problem() if isinstance(err, bx.PackageError) else {"kind": "fetch-error", "path": "", "message": str(err)}
            problems.append({**problem, "package": name})
            log(f"[loadorders] {slug}: dependency {name} failed: {err}")
    for full in chain["missing"]:  # dependencies first, the target last
        r, wanted, fell_back, downloaded = resolved[full]
        is_target = full == ref.full_name
        try:
            if is_target and target_installer is not None:
                entry = target_installer(r)
            elif downloaded:
                entry = _extract(app_root, slug, r, ts.ensure_cached(app_root, r, None, app_version), False)
            elif is_target and not fallback_latest:
                entry = _fetch_and_install(app_root, slug, r, False, app_version)
            else:
                entry, late = _fetch_pinned_or_latest(app_root, slug, r, False, app_version)
                fell_back = fell_back or late
        except (ts.ThunderstoreError, bx.PackageError) as err:
            if is_target:
                raise
            problem = getattr(err, "problem", lambda: {"kind": "fetch-error", "path": "", "message": str(err)})()
            problems.append({**problem, "package": full})
            log(f"[loadorders] {slug}: dependency {full} failed: {err}")
            continue
        if fell_back and wanted:
            fallbacks.append({"package": full, "wanted": wanted, "installed": entry["version"]})
        left_out = [d for d in _declared_dependencies(entry) if d in chain["skipped"]]
        if left_out:
            entry["skipped_dependencies"] = left_out  # dependency_issues: never "missing"
        have[full] = entry
        manifest["active"].append(entry)
        done.append(entry)
        _write(app_root, slug, manifest)  # keep the manifest truthful after every install
    log(f"[loadorders] {slug}: installed {[e['full_name'] for e in done]}, {len(problems)} problems, "
        f"{len(fallbacks)} fallbacks {fallbacks}")
    return {"installed": done, "problems": problems, "fallbacks": fallbacks}


def _zip_dependencies_strict(app_root, ref: ts.PackageRef, zip_path) -> list[str]:
    """A just-downloaded zip's dependency strings; a corrupt one is evicted
    and the PackageError raised (the fallback / problem path)."""
    try:
        with bx.PackageSource(zip_path) as src:
            return list(bx.read_manifest(src)["dependencies"])
    except bx.PackageError as err:
        if err.kind == "bad-zip":
            ts.evict_cached(app_root, ref)
        raise


# ---- Import local mod (THUNDERSTORE.md §8b) ----
LOCAL_NAMESPACE = "Local"  # the owner when neither the file name nor manifest.json names a usable one


def inspect_local_package(zip_path) -> dict:
    """Validates a locally picked package zip - no network, nothing written.
    Returns {"ref": versioned PackageRef (the identity it installs under),
    "manifest": the parsed manifest.json, "owner_source": "filename" |
    "author" | "fallback", "files": entry count}. PackageError (kinds as
    bepinex_install's: "bad-zip", "no-manifest", "parse-error", "bad-path")
    for anything that can't be installed - the dialog shows its message.

    Identity: name + version always come from manifest.json (and must be a
    valid Thunderstore name / major.minor.patch - the cache key and every
    dependency string rely on it). The owner (namespace) comes from the file
    name when it is Thunderstore's own download name "Owner-Name-Version.zip"
    (or "Owner-Name.zip") whose Name matches the manifest's - so a real
    Thunderstore zip keeps the identity other mods' dependency strings use;
    else manifest.json's non-standard "author" field if it's a valid
    namespace; else LOCAL_NAMESPACE."""
    path = Path(zip_path)
    if not path.is_file():
        raise bx.PackageError("bad-zip", path, f"Not a file: {path}")
    with bx.PackageSource(path) as src:
        manifest = bx.read_manifest(src)
        n_files = len(src.files())
    name, version = manifest["name"], manifest["version_number"]
    try:
        ts.PackageRef(LOCAL_NAMESPACE, name)
    except ValueError:
        raise bx.PackageError("parse-error", path, f"manifest.json's name {name!r} isn't a valid Thunderstore package "
                                                   "name (letters, digits and _ only)") from None
    if ts.version_key(version) == (-1,):
        raise bx.PackageError("parse-error", path, f"manifest.json's version_number {version!r} isn't a "
                                                   "major.minor.patch version")
    owner, source = None, "fallback"
    try:
        from_file = ts.PackageRef.parse(path.stem)
        if from_file.name.lower() == name.lower():
            owner, source = from_file.namespace, "filename"
            if from_file.version and from_file.version != version:
                log(f"[loadorders] local import {path.name}: file name says {from_file.version}, manifest.json "
                    f"{version} - the manifest wins")
    except ValueError:
        pass
    if owner is None and isinstance(manifest.get("author"), str):
        try:
            owner, source = ts.PackageRef(manifest["author"].strip(), name).namespace, "author"
        except ValueError:
            pass
    ref = ts.PackageRef(owner or LOCAL_NAMESPACE, name, version)
    log(f"[loadorders] local import {path}: {ref.key} (owner from {source}), {n_files} files, "
        f"{len(manifest['dependencies'])} dependencies")
    return {"ref": ref, "manifest": manifest, "owner_source": source, "files": n_files}


def _cache_local_zip(app_root, zip_path, ref: ts.PackageRef) -> Path:
    """Copies the picked zip into the shared package cache as <key>.zip
    (temp sibling + os.replace, like a download). An existing cached zip of
    that exact key is replaced: the cache then holds what this tree got."""
    dest = ts.package_cache_dir(app_root) / f"{ref.key}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    had = dest.stat().st_size if dest.is_file() else None
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.part")
    try:
        shutil.copyfile(zip_path, tmp)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    log(f"[loadorders] local import: {zip_path} -> {dest} ({dest.stat().st_size} bytes"
        f"{'' if had is None else f', replaced a cached {had}-byte zip of the same version'})")
    return dest


def import_local_mod(app_root, slug, game: ThunderstoreGame, zip_path, app_version=None) -> dict:
    """Installs a locally picked package zip into the load order exactly as
    install_mod() installs a download (same already-installed / framework
    guard, same routing, appended to Active enabled, its missing
    dependencies from Thunderstore): only the zip's source differs. The
    entry is recorded online_source: false (never update-checked). Returns
    install_mod()'s dict plus "ref" (the identity it got) and
    "owner_source"; "installed" is empty when that package is already in
    the load order (or is the framework). PackageError for a zip that
    can't be installed."""
    info = inspect_local_package(zip_path)
    ref = info["ref"]

    def install_local(r: ts.PackageRef) -> dict:
        cached = _cache_local_zip(app_root, zip_path, ref)
        result = bx.install_package(cached, tree_root(app_root, slug), ref.full_name, framework=False)
        return {**_make_entry(ref, result), "online_source": False}

    res = install_mod(app_root, slug, game, ref, app_version, target_installer=install_local,
                      target_dependencies=info["manifest"]["dependencies"])
    log(f"[loadorders] {slug}: local import of {zip_path} as {ref.key}: "
        f"{'installed' if res['installed'] else 'already installed, nothing done'}")
    return {**res, "ref": ref, "owner_source": info["owner_source"]}


def remove_mod(app_root, slug, full_name: str) -> dict:
    """Deletes a mod's files from the tree (config kept) and drops it from
    the manifest. The framework can't be removed. Returns the new manifest."""
    manifest = load_load_order(app_root, slug)
    fw = manifest.get("framework")
    if fw and fw["full_name"] == full_name:
        raise ValueError(f"{full_name} is the framework package and can't be removed")
    entry = installed(manifest).get(full_name)
    if entry is None:
        raise ValueError(f"{full_name} is not installed in this profile")
    res = bx.remove_files(tree_root(app_root, slug), entry["files"])
    log(f"[loadorders] {slug}: removed {full_name}: {res}")
    manifest["active"] = [e for e in manifest["active"] if e["full_name"] != full_name]
    manifest["inactive"] = [e for e in manifest["inactive"] if e["full_name"] != full_name]
    return _write(app_root, slug, manifest)


def save_load_order(app_root, slug, active, inactive) -> dict:
    """Save (THUNDERSTORE.md §3's one button): `active` = ordered list of
    full_names or {"full_name", "enabled"} dicts, `inactive` = list of
    full_names. Every installed mod (except the framework, which is pinned and
    must not be passed) has to appear exactly once across the two; the
    on-disk enable/disable state of every mod is then materialized to match.
    Returns the new manifest."""
    manifest = load_load_order(app_root, slug)
    have = installed(manifest)
    fw = manifest["framework"]["full_name"] if manifest.get("framework") else None
    seen = set()

    def take(item, enabled_default: bool) -> dict:
        if isinstance(item, dict):
            name, enabled = item.get("full_name"), item.get("enabled", enabled_default)
        else:
            name, enabled = item, enabled_default
        if name == fw:
            raise ValueError(f"{name} is the framework package: pinned, not part of the lists")
        if name not in have:
            raise ValueError(f"{name!r} is not installed in this profile")
        if name in seen:
            raise ValueError(f"{name} is listed twice")
        seen.add(name)
        return {**have[name], "enabled": bool(enabled)}

    new_active = [take(i, True) for i in (active or [])]
    new_inactive = [{**take(i, False), "enabled": True} for i in (inactive or [])]
    missing = [n for n in have if n != fw and n not in seen]
    if missing:
        raise ValueError(f"Installed mods missing from both lists: {', '.join(missing)}")
    root = tree_root(app_root, slug)
    drift = []
    for e in new_active:
        drift += bx.set_files_enabled(root, e["files"], e["enabled"])["missing"]
    for e in new_inactive:
        drift += bx.set_files_enabled(root, e["files"], False)["missing"]
    if drift:
        log(f"[loadorders] {slug}: save: {len(drift)} tracked files missing from the tree: {drift[:10]}")
    manifest["active"], manifest["inactive"] = new_active, new_inactive
    log(f"[loadorders] {slug}: saved {len(new_active)} active ({sum(1 for e in new_active if not e['enabled'])} off), {len(new_inactive)} inactive")
    return _write(app_root, slug, manifest)


def set_mod_enabled(app_root, slug, full_name: str, enabled: bool) -> dict:
    """One active mod's toggle, materialized immediately (a Save of the
    current lists with just that flag changed). Returns the new manifest."""
    manifest = load_load_order(app_root, slug)
    if full_name not in {e["full_name"] for e in manifest["active"]}:
        raise ValueError(f"{full_name} is not in the active list")
    active = [{"full_name": e["full_name"], "enabled": enabled if e["full_name"] == full_name else e["enabled"]}
              for e in manifest["active"]]
    return save_load_order(app_root, slug, active, [e["full_name"] for e in manifest["inactive"]])


def _check_one(entry: dict, latest_version: str, date_updated, deprecated) -> dict:
    return {"latest_version": latest_version, "date_updated": date_updated if isinstance(date_updated, str) else None,
            "update": ts.is_newer(latest_version, entry["version"]), "deprecated": bool(deprecated)}


def _check_per_package(todo: list, app_version) -> dict[str, dict]:
    """check_updates' per-package path: one fetch_package per (full_name,
    entry), FETCH_WORKERS at a time, no pause between them (0.6.52; was one
    at a time 250 ms apart: ~3 min for 300 mods) - fetch_package's own HTTP
    429 retry / back-off paces it, as it does the dependency chain's
    lookups. Once one is still rate-limited after those retries, no new
    request starts: the rest get that same error."""
    out: dict[str, dict] = {}
    limited: list[str] = []
    not_asked: list[str] = []

    def one(item) -> None:
        full_name, entry = item
        if limited:
            out[full_name] = {"error": limited[0]}
            not_asked.append(full_name)
            return
        try:
            meta = ts.fetch_package(entry["namespace"], entry["name"], app_version)
        except ts.RateLimitedError as err:
            limited.append(str(err))
            out[full_name] = {"error": str(err)}
            return
        except ts.ThunderstoreError as err:
            out[full_name] = {"error": str(err)}
            return
        out[full_name] = _check_one(entry, meta["latest"]["version_number"], meta.get("date_updated"),
                                    meta.get("is_deprecated"))

    tb._parallel(todo, one, tb.FETCH_WORKERS)
    if limited:
        log(f"[loadorders] update check: rate-limited, didn't ask for the other {len(not_asked)} packages")
    return {n: out.get(n, {"error": "The update check failed for this mod."}) for n, _ in todo}


def check_updates(manifest: dict, app_version=None, only=None, *, app_root=None, community: str | None = None) -> dict[str, dict]:
    """Every installed package with online_source (framework included), or
    only those full_names in `only` when given: full_name ->
    {"latest_version", "date_updated", "update": bool, "deprecated": bool}
    or {"error": str} (that package's check failed - the rest still get
    checked; once Thunderstore is rate-limiting past fetch_package's
    retries, the rest aren't asked and get that same error). 0.6.52: with
    `app_root` + `community`, answered from the community index
    (thunderstore_index.ensure at UPDATE_MAX_AGE_S - built here when over an
    hour old, "indexing" on the download bar meanwhile, inside
    package_progress) with no request; per package (_check_per_package)
    only for what it lacks, an installed version newer than its latest (it
    is behind), or everything when it can't be built. Pure network +
    compare, nothing written; the caller keeps/caches the result."""
    todo = [(n, e) for n, e in installed(manifest).items()
            if e.get("online_source", True) and (only is None or n in only)]
    index = None
    if todo and app_root is not None and community:
        built = []
        index = pi.ensure(app_root, community, app_version, max_age_s=pi.UPDATE_MAX_AGE_S,
                          on_build=lambda: (built.append(1), _emit({"type": "indexing"})))  # "Updating package list..."
        if built:
            _emit({"type": "plan", "ids": []})  # the bar's "Updating package list..." ends
    out, ask = {}, []
    for full_name, entry in todo:
        hit = index.latest(full_name) if index is not None else None
        if hit is None or ts.is_newer(entry["version"], hit["latest_version"]):
            ask.append((full_name, entry))  # not in the index (newer than it, another game's), or it is behind
        else:
            out[full_name] = _check_one(entry, **hit)
    out.update(_check_per_package(ask, app_version) if ask else {})
    out = {n: out[n] for n, _ in todo}
    log(f"[loadorders] update check: {sum(1 for v in out.values() if v.get('update'))} of {len(out)} packages have an update, "
        f"{sum(1 for v in out.values() if 'error' in v)} failed; {len(todo) - len(ask)} from the package index, "
        f"{len(ask)} asked per package")
    return out


def update_mod(app_root, slug, game: ThunderstoreGame, full_name: str, app_version=None, *, version: str | None = None,
               reinstall: bool = False) -> dict:
    """Re-downloads + installs `full_name` at Thunderstore's current latest
    version - or at `version` (the browser's Versions tab: any release,
    newer or older) - in place (the framework included). New files
    overwrite the tree's, files the old version tracked that the new one
    doesn't are deleted (the config files it ships overwritten, 0.6.51); the mod's on-disk state
    and list position are preserved (an inactive or toggled-off mod comes
    back disabled). Returns {"manifest", "entry", "updated": bool} -
    updated False when the installed version already is the one asked for
    (nothing touched). ValueError for a package not in this load order or
    a bad version; ThunderstoreError / PackageError from the fetch/install.
    `reinstall` (with `version` = the installed one; reinstall_mod): install
    it again anyway, putting back files missing from the tree."""
    manifest = load_load_order(app_root, slug)
    entry = installed(manifest).get(full_name)
    if entry is None:
        raise ValueError(f"{full_name} is not installed in this profile")
    fw = manifest.get("framework")
    is_framework = bool(fw) and fw["full_name"] == full_name
    if version is None:
        meta = ts.fetch_package(entry["namespace"], entry["name"], app_version)
        latest = ts.latest_ref(meta)
        if not ts.is_newer(latest.version, entry["version"]):
            log(f"[loadorders] {slug}: {full_name} {entry['version']} is current (latest {latest.version}), nothing to update")
            return {"manifest": manifest, "entry": entry, "updated": False}
    else:
        latest = ts.PackageRef(entry["namespace"], entry["name"], version)  # validates; "latest" = the target below
        if version == entry["version"] and not reinstall:
            log(f"[loadorders] {slug}: {full_name} already is {version}, nothing to do")
            return {"manifest": manifest, "entry": entry, "updated": False}
    on_disk_enabled = is_framework or (
        entry["enabled"] and any(e["full_name"] == full_name for e in manifest["active"]))
    root = tree_root(app_root, slug)
    new = _fetch_and_install(app_root, slug, latest, framework=is_framework, app_version=app_version)
    if not on_disk_enabled:
        bx.set_files_enabled(root, new["files"], False)
    stale = [f for f in entry["files"] if f not in set(new["files"])]
    if stale:
        res = bx.remove_files(root, stale)
        log(f"[loadorders] {slug}: {full_name} update dropped {len(stale)} files of {entry['version']}: {res}")
    new_entry = {**entry, **new, "enabled": entry["enabled"], "online_source": entry.get("online_source", True),
                 "config_sha256": {**(entry.get("config_sha256") if isinstance(entry.get("config_sha256"), dict) else {}),
                                   **new["config_sha256"]}}  # what every version wrote (a record; 0.6.51: it overwrote its own)
    if is_framework:
        manifest["framework"] = new_entry
    else:
        for key in ("active", "inactive"):
            manifest[key] = [new_entry if e["full_name"] == full_name else e for e in manifest[key]]
    log(f"[loadorders] {slug}: {'updated' if version is None else 'reinstalled' if reinstall else 'switched'} {full_name} {entry['version']} -> {latest.version}"
        f"{' (framework)' if is_framework else ''}{'' if on_disk_enabled else ', kept disabled'}")
    return {"manifest": _write(app_root, slug, manifest), "entry": new_entry, "updated": True}


def reinstall_mod(app_root, slug, game: ThunderstoreGame, full_name: str, app_version=None) -> dict:
    """The Missing files fix (module docstring): `full_name` extracted again
    at its installed version - from the cached zip, else downloaded through
    the normal path - over the tree (update_mod(reinstall=True): on-disk
    enabled / disabled state and list position kept, its own config files
    written again (0.6.51); no other mod touched). Returns update_mod's dict plus "source" ("cache" /
    "download") and "missing_before" / "missing_after" (that mod's missing
    file count). ValueError (plain words) for a local .zip mod with no
    cached copy; ThunderstoreError / PackageError from the fetch/install."""
    manifest = load_load_order(app_root, slug)
    entry = installed(manifest).get(full_name)
    if entry is None:
        raise ValueError(f"{full_name} is not installed in this profile")
    source = reinstall_source(app_root, entry)
    if source is None:
        raise ValueError(f"VOLT no longer has the .zip file {entry['display_name']} was added from, so it can't put its files back.")
    before = missing_files(app_root, slug, manifest).get(full_name, (0, 0))[0]
    log(f"[loadorders] {slug}: reinstall {full_name} {entry['version']}: from the {source}, "
        f"{before} of {len([f for f in entry['files'] if not bx.is_config_path(f)])} files missing before")
    res = update_mod(app_root, slug, game, full_name, app_version, version=entry["version"], reinstall=True)
    after = missing_files(app_root, slug, res["manifest"]).get(full_name, (0, 0))[0]
    log(f"[loadorders] {slug}: reinstall {full_name}: done, {len(res['entry']['files'])} files tracked, "
        f"{after} still missing")
    return {**res, "source": source, "missing_before": before, "missing_after": after}


def copy_load_order(app_root, slug, new_name: str) -> dict:
    """Duplicates a load order's whole tree (files + manifest, enabled/
    disabled state included) under a new name, minus the run history
    (volt-runs/, 0.6.41: those runs belong to the original). Returns the new
    manifest."""
    src = load_load_order(app_root, slug)  # validates the source first
    display, new_slug = _allocate(app_root, new_name)
    dst = tree_root(app_root, new_slug)
    top = tree_root(app_root, slug)
    try:
        shutil.copytree(top, dst, dirs_exist_ok=True,
                        ignore=lambda d, names: ["volt-runs"] if Path(d) == top and "volt-runs" in names else [])
    except Exception:
        remove_tree_best_effort(dst)
        raise
    now = _now()
    manifest = {**{k: v for k, v in src.items() if k != "slug"}, "name": display, "created_at": now}
    log(f"[loadorders] copied {slug!r} -> {new_slug!r} ({display!r})")
    return _write(app_root, new_slug, manifest)


def reclaim_slug(app_root, slug) -> str:
    """After a replace (bepinex_share.replace_profile): move the load order's
    folder to the slug its name would get now, i.e. _allocate's first free
    candidate, so a same-name replace doesn't leave <slug>-2 behind. Only a
    plain rename - nothing records the folder path (manifests don't store the
    slug, launch paths are computed per run). A failed rename (a file held
    open on Windows) keeps the working folder and is only logged. Returns the
    slug in use."""
    base = slugify(load_load_order(app_root, slug)["name"])
    root = load_orders_root(app_root)
    for n in range(1, 1000):
        cand = base if n == 1 else f"{base}-{n}"
        if cand == slug:
            return slug
        if not (root / cand).exists():
            try:
                os.rename(root / slug, root / cand)
            except OSError as err:
                log(f"[loadorders] rename {slug!r} -> {cand!r} failed ({err!r}); keeping {slug!r}")
                return slug
            log(f"[loadorders] renamed {slug!r} -> {cand!r}")
            return cand
    return slug


def delete_load_order(app_root, slug) -> dict:
    """Removes the load order's whole folder (tree and manifest). Permanent -
    the caller confirms first. Best effort: a file the running game holds
    open is reported in the result's "skipped", not raised."""
    root = tree_root(app_root, slug)  # assert_slug: never remove a path built from an unchecked slug
    res = remove_tree_best_effort(root)
    log(f"[loadorders] deleted {slug!r}: {res}")
    return res


# ---- Clean cache (THUNDERSTORE.md §8c) ----
def unreferenced_cache_files(file_names, manifests) -> dict[str, list[str]]:
    """Pure (no I/O): sorts the shared package cache's file names (bare names
    of the files directly in cache/packages/) against every load order's
    manifest (normalized, as load_load_order returns them). Returns
    {"remove": [...], "keep": [...], "ignored": [...]}, each sorted:
    - keep: "<Team-Package-Version>.zip" whose key is the framework / an
      active / an inactive entry's full_name + version in any manifest. An
      entry whose version isn't major.minor.patch keeps every cached version
      of its full_name (its exact key can't be built - never guess).
    - remove: every other "<Team-Package-Version>.zip".
    - ignored: anything else (a download's "<key>.zip.<pid>.part" temp file,
      a stray file) - never removed.
    Compared case-insensitively: on Windows "A.zip" and "a.zip" are one file."""
    keys, any_version = set(), set()
    for m in manifests:
        for e in installed(m).values():
            if ts.version_key(e.get("version")) == (-1,):
                any_version.add(e["full_name"].lower())
            else:
                keys.add(f"{e['full_name']}-{e['version']}".lower())
    out = {"remove": [], "keep": [], "ignored": []}
    for name in sorted(file_names, key=str.lower):
        ref = None
        if name.lower().endswith(".zip"):
            try:
                ref = ts.PackageRef.parse(name[:-4])
            except ValueError:
                pass
        if ref is None or ref.version is None:
            out["ignored"].append(name)
        elif ref.key.lower() in keys or ref.full_name.lower() in any_version:
            out["keep"].append(name)
        else:
            out["remove"].append(name)
    return out


def clean_package_cache(app_root) -> dict:
    """Clean cache: deletes every cached package zip that no load order of
    this game (every load order under this APP-ROOT) references, active or
    inactive list or framework (unreferenced_cache_files). If any load
    order's manifest can't be read, nothing is deleted - never sweep on
    incomplete information. The caller makes sure no install / download is
    running meanwhile (the screen's busy state).
    Since 0.6.31 it also empties the Browse Mods README image cache
    (thunderstore_browse.prune_image_cache with a zero cap: those pictures
    are fully regenerable), unless it aborted.
    Returns {"unreadable": [{"slug", "error"}] (non-empty = aborted, nothing
    deleted), "load_orders": count read, "removed": [(name, bytes)],
    "freed": bytes, "failed": [(name, error)], "kept": [names], "ignored":
    [names], "images": prune_image_cache's {"total", "removed", "freed",
    "failed"}}. OSError if a folder itself can't be listed."""
    res = {"unreadable": [], "load_orders": 0, "removed": [], "freed": 0, "failed": [], "kept": [], "ignored": [],
           "images": {"total": 0, "removed": 0, "freed": 0, "failed": 0}}
    manifests = []
    try:
        dirs = sorted(e.name for e in os.scandir(load_orders_root(app_root)) if e.is_dir())
    except FileNotFoundError:
        dirs = []
    for slug in dirs:
        if not is_valid_slug(slug):  # list_load_orders' rule: never a load order VOLT can open
            log(f"[cache] clean: skipping {slug!r} (not a load order folder name)")
            continue
        try:
            m = load_load_order(app_root, slug)
        except Exception as err:
            res["unreadable"].append({"slug": slug, "error": str(err) or repr(err)})
            log(f"[cache] clean: load order {slug!r} can't be read: {err!r}")
            continue
        manifests.append(m)
        refs = [f"{e['full_name']}-{e['version']}" for e in installed(m).values()]
        log(f"[cache] clean: load order {slug!r} references {len(refs)} packages: {refs}")
    res["load_orders"] = len(manifests)
    if res["unreadable"]:
        log(f"[cache] clean ABORTED, nothing deleted: {len(res['unreadable'])} unreadable load order(s): {res['unreadable']}")
        return res
    cache = ts.package_cache_dir(app_root)
    try:
        entries = list(os.scandir(cache))
    except FileNotFoundError:
        entries = []
    names = [e.name for e in entries if e.is_file(follow_symlinks=False)]
    others = [e.name for e in entries if not e.is_file(follow_symlinks=False)]  # a folder / link: left alone
    plan = unreferenced_cache_files(names, manifests)
    res["kept"], res["ignored"] = plan["keep"], sorted(plan["ignored"] + others)
    log(f"[cache] clean {cache}: {len(manifests)} load orders read, {len(names)} files - {len(plan['keep'])} kept "
        f"{plan['keep']}, {len(plan['remove'])} to remove, {len(res['ignored'])} left alone {res['ignored']}")
    for name in plan["remove"]:
        p = cache / name
        try:
            size = p.stat().st_size
            p.unlink()
        except OSError as err:
            res["failed"].append((name, str(err) or repr(err)))
            log(f"[cache] clean: FAILED to remove {name}: {err!r}")
            continue
        res["removed"].append((name, size))
        res["freed"] += size
        log(f"[cache] clean: removed {name} ({size} bytes)")
    res["images"] = tb.prune_image_cache(app_root, cap=0, target=0)  # README pictures: all go (0.6.31)
    log(f"[cache] clean done: removed {len(res['removed'])} ({res['freed']} bytes freed), "
        f"{len(res['failed'])} failed, {len(res['kept'])} kept; README images: {res['images']['removed']} removed "
        f"({res['images']['freed']} bytes), {res['images']['failed']} failed")
    return res
