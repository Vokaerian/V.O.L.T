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
  "dependencies": ["denikson-BepInExPack_Valheim-5.4.2333", ...],  # as declared, informational
  "enabled": true,               # active-list toggle; always true for framework/inactive-irrelevant
  "online_source": true,         # false = imported from a local zip (THUNDERSTORE.md §8b):
                                 #   never update-checked; absent in older manifests = true
  "installed_at": "<ISO>",
  "files": ["BepInEx/plugins/ValheimModding-Jotunn/Jotunn.dll", ...]  # tree-relative, enabled names
}
On disk, a mod's files are enabled (plain names) iff it is in `active` with
enabled=true; `inactive` mods and toggled-off active mods are renamed with
bepinex_install.DISABLED_SUFFIX. save_load_order() is the one place that
materializes this. Unknown top-level fields are preserved.

Network goes through thunderstore.py (fetch_package / ensure_cached), so the
check harness fakes thunderstore.env.urlopen. Dependency auto-install
(THUNDERSTORE.md §1): install_mod() pulls in every declared dependency not yet
installed, recursively, at its LATEST version - a dependency string's version
is informational, not a pin (TMM's own profiles show the same). A dependency
that can't be fetched/installed is reported as a problem, not a failure of
the whole install; the requested package failing raises.

Updates (THUNDERSTORE.md §3, stage 3b): check_updates() asks Thunderstore for
every installed package's current latest version (online_source ones only)
and update_mod() re-downloads + installs one package (the framework
included) in place - new files overwrite, files the old version had and the
new one doesn't are deleted, config kept, the mod's on-disk enabled/disabled
state preserved. The manager screen runs both off the GUI thread.

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
"""

import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import bepinex_install as bx
from . import thunderstore as ts
from .applog import log
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
    """The full_names an installed entry declares (bad strings skipped, each once)."""
    out: list[str] = []
    for dep in (entry or {}).get("dependencies", ()):
        try:
            name = ts.PackageRef.parse(dep).full_name
        except ValueError:
            continue
        if name not in out:
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
        raise ValueError("Load order name is empty")
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
    raise ValueError(f'Too many load orders named like "{display}"')


def _make_entry(ref: ts.PackageRef, result: dict) -> dict:
    m = result["manifest"]
    return {
        "full_name": ref.full_name, "namespace": ref.namespace, "name": ref.name,
        "version": m["version_number"], "display_name": m["name"],
        "description": m["description"], "website_url": m["website_url"],
        "dependencies": list(m["dependencies"]),
        "enabled": True, "online_source": True, "installed_at": _now(),
        "files": list(result["files"]),
    }


def _fetch_and_install(app_root, slug, ref: ts.PackageRef, framework: bool, app_version=None) -> dict:
    """Resolve `ref` (a pinned version, else Thunderstore's latest), get the
    zip into the shared cache, extract it into the tree. Returns the entry."""
    url = None
    if ref.version is None:
        meta = ts.fetch_package(ref.namespace, ref.name, app_version)
        ref = ts.latest_ref(meta)
        url = meta["latest"].get("download_url") if isinstance(meta["latest"].get("download_url"), str) else None
    zip_path = ts.ensure_cached(app_root, ref, url, app_version)
    root = tree_root(app_root, slug)
    try:
        result = bx.install_package(zip_path, root, ref.full_name, framework=framework)
    except bx.PackageError as err:
        if err.kind == "bad-zip":  # a corrupt cached download: don't keep serving it
            ts.evict_cached(app_root, ref)
        raise
    return _make_entry(ref, result)


def _fetch_pinned_or_latest(app_root, slug, ref: ts.PackageRef, framework: bool, app_version=None) -> tuple[dict, bool]:
    """_fetch_and_install for a pinned `ref` (an import's exact version): if
    that version can't be fetched or installed (gone from Thunderstore, a
    bad download), the package's latest is installed instead. Returns
    (entry, fell_back). An unpinned ref is just _fetch_and_install."""
    try:
        return _fetch_and_install(app_root, slug, ref, framework=framework, app_version=app_version), False
    except (ts.ThunderstoreError, bx.PackageError) as err:
        if ref.version is None:
            raise
        log(f"[loadorders] {slug}: {ref.key} unavailable ({err}); falling back to the latest {ref.full_name}")
    entry = _fetch_and_install(app_root, slug, ts.PackageRef(ref.namespace, ref.name), framework=framework, app_version=app_version)
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


def install_mod(app_root, slug, game: ThunderstoreGame, target, app_version=None, *,
                pins: dict[str, str] | None = None, fallback_latest: bool = False, target_installer=None) -> dict:
    """Installs `target` (a PackageRef or "Team-Package[-Version]" string) into
    the load order, appended to the active list enabled, after any of its
    declared dependencies not yet installed (recursively, latest versions -
    or the version `pins` names for that full_name: an import's file
    pins every package it lists, bepinex_share.py). Already-installed
    packages (framework included) are left alone. Returns {"installed":
    [entries, dependencies first], "problems": [{kind, path, message,
    package}], "fallbacks": [{package, wanted, installed}]} - a dependency
    that fails is a problem; the target itself failing raises
    (ThunderstoreError / PackageError). With `fallback_latest`, a pinned
    version that can't be fetched (gone from Thunderstore) is replaced by
    the package's latest and recorded in "fallbacks" instead of failing;
    without it (the browser's Versions tab), a pinned version is exact.
    `target_installer(ref) -> entry` replaces the target's own fetch +
    install (import_local_mod: the picked zip instead of a download);
    dependencies still come from Thunderstore."""
    ref = target if isinstance(target, ts.PackageRef) else ts.PackageRef.parse(target)
    manifest = load_load_order(app_root, slug)
    have = installed(manifest)
    if ref.full_name == game.framework_package or ref.full_name in have:
        log(f"[loadorders] {slug}: {ref.full_name} already installed, nothing to do")
        return {"installed": [], "problems": [], "fallbacks": []}
    done, problems, fallbacks, visiting = [], [], [], set()

    def visit(r: ts.PackageRef, is_target: bool) -> None:
        if r.full_name in have or r.full_name == game.framework_package or r.full_name in visiting:
            return
        visiting.add(r.full_name)
        if r.version is None and pins and pins.get(r.full_name):
            r = r.with_version(pins[r.full_name])
        try:
            if is_target and target_installer is not None:
                entry, fell_back = target_installer(r), False
            elif fallback_latest:
                entry, fell_back = _fetch_pinned_or_latest(app_root, slug, r, framework=False, app_version=app_version)
            else:
                entry, fell_back = _fetch_and_install(app_root, slug, r, framework=False, app_version=app_version), False
        except (ts.ThunderstoreError, bx.PackageError) as err:
            if is_target:
                raise
            problem = getattr(err, "problem", lambda: {"kind": "fetch-error", "path": "", "message": str(err)})()
            problems.append({**problem, "package": r.full_name})
            log(f"[loadorders] {slug}: dependency {r.full_name} failed: {err}")
            return
        if fell_back:
            fallbacks.append({"package": r.full_name, "wanted": r.version, "installed": entry["version"]})
        for dep in entry["dependencies"]:
            try:
                d = ts.PackageRef.parse(dep)
                visit(ts.PackageRef(d.namespace, d.name), False)  # the dep string's version is informational: latest (or a pin)
            except ValueError as err:
                problems.append({"kind": "bad-dependency", "path": "", "message": str(err), "package": r.full_name})
        have[entry["full_name"]] = entry
        manifest["active"].append(entry)
        done.append(entry)
        _write(app_root, slug, manifest)  # keep the manifest truthful after every install

    visit(ref, True)
    log(f"[loadorders] {slug}: installed {[e['full_name'] for e in done]}, {len(problems)} problems, {len(fallbacks)} fallbacks")
    return {"installed": done, "problems": problems, "fallbacks": fallbacks}


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

    res = install_mod(app_root, slug, game, ref, app_version, target_installer=install_local)
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
        raise ValueError(f"{full_name} is not installed in this load order")
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
            raise ValueError(f"{name!r} is not installed in this load order")
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


def check_updates(manifest: dict, app_version=None) -> dict[str, dict]:
    """One Thunderstore metadata fetch per installed package with
    online_source (framework included): full_name -> {"latest_version",
    "date_updated", "update": bool, "deprecated": bool (the same reply's
    is_deprecated)} or {"error": str} (that package's
    fetch failed - the rest still get checked). Pure network + compare,
    nothing written; the caller keeps/caches the result."""
    out = {}
    for full_name, entry in installed(manifest).items():
        if not entry.get("online_source", True):
            continue
        try:
            meta = ts.fetch_package(entry["namespace"], entry["name"], app_version)
        except ts.ThunderstoreError as err:
            out[full_name] = {"error": str(err)}
            continue
        latest = meta["latest"]["version_number"]
        out[full_name] = {
            "latest_version": latest,
            "date_updated": meta.get("date_updated") if isinstance(meta.get("date_updated"), str) else None,
            "update": ts.is_newer(latest, entry["version"]),
            "deprecated": bool(meta.get("is_deprecated")),
        }
    log(f"[loadorders] update check: {sum(1 for v in out.values() if v.get('update'))} of {len(out)} packages have an update, "
        f"{sum(1 for v in out.values() if 'error' in v)} failed")
    return out


def update_mod(app_root, slug, game: ThunderstoreGame, full_name: str, app_version=None, *, version: str | None = None) -> dict:
    """Re-downloads + installs `full_name` at Thunderstore's current latest
    version - or at `version` (the browser's Versions tab: any release,
    newer or older) - in place (the framework included). New files
    overwrite the tree's, files the old version tracked that the new one
    doesn't are deleted (config kept, as always); the mod's on-disk state
    and list position are preserved (an inactive or toggled-off mod comes
    back disabled). Returns {"manifest", "entry", "updated": bool} -
    updated False when the installed version already is the one asked for
    (nothing touched). ValueError for a package not in this load order or
    a bad version; ThunderstoreError / PackageError from the fetch/install."""
    manifest = load_load_order(app_root, slug)
    entry = installed(manifest).get(full_name)
    if entry is None:
        raise ValueError(f"{full_name} is not installed in this load order")
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
        if version == entry["version"]:
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
    new_entry = {**entry, **new, "enabled": entry["enabled"], "online_source": entry.get("online_source", True)}
    if is_framework:
        manifest["framework"] = new_entry
    else:
        for key in ("active", "inactive"):
            manifest[key] = [new_entry if e["full_name"] == full_name else e for e in manifest[key]]
    log(f"[loadorders] {slug}: {'updated' if version is None else 'switched'} {full_name} {entry['version']} -> {latest.version}"
        f"{' (framework)' if is_framework else ''}{'' if on_disk_enabled else ', kept disabled'}")
    return {"manifest": _write(app_root, slug, manifest), "entry": new_entry, "updated": True}


def copy_load_order(app_root, slug, new_name: str) -> dict:
    """Duplicates a load order's whole tree (files + manifest, enabled/
    disabled state included) under a new name. Returns the new manifest."""
    src = load_load_order(app_root, slug)  # validates the source first
    display, new_slug = _allocate(app_root, new_name)
    dst = tree_root(app_root, new_slug)
    try:
        shutil.copytree(tree_root(app_root, slug), dst, dirs_exist_ok=True)
    except Exception:
        remove_tree_best_effort(dst)
        raise
    now = _now()
    manifest = {**{k: v for k, v in src.items() if k != "slug"}, "name": display, "created_at": now}
    log(f"[loadorders] copied {slug!r} -> {new_slug!r} ({display!r})")
    return _write(app_root, new_slug, manifest)


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
    Returns {"unreadable": [{"slug", "error"}] (non-empty = aborted, nothing
    deleted), "load_orders": count read, "removed": [(name, bytes)],
    "freed": bytes, "failed": [(name, error)], "kept": [names], "ignored":
    [names]}. OSError if a folder itself can't be listed."""
    res = {"unreadable": [], "load_orders": 0, "removed": [], "freed": 0, "failed": [], "kept": [], "ignored": []}
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
    log(f"[cache] clean done: removed {len(res['removed'])} ({res['freed']} bytes freed), "
        f"{len(res['failed'])} failed, {len(res['kept'])} kept")
    return res
