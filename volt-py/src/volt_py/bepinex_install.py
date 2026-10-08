"""BepInEx install routing for Thunderstore packages (THUNDERSTORE.md §1) -
game-agnostic: where each file of a package zip lands inside a load order's
BepInEx tree, plus the per-mod enable/disable and removal file operations
Save builds on (§2). No network, no Qt; the tree root is any folder.

Routing (0.6.53: Gale's SubdirInstaller for BepInEx, flat_separated
subdirs; until 0.6.52 only the first component counted and sub-paths were
kept, which broke qwbarch-MirageCore's FSharp.Core/ load). Paths are taken
relative to the zip root; walking the components from the left, the FIRST
one (at any depth) that triggers a route decides - `plugins`, `patchers`,
`monomod`, `core`, `config` (folder name, any case) or a name ending in
`.mm.dll` (monomod; case-sensitive, as Gale's extension match). Everything
before it is dropped, everything after it kept:
  - `[x/]config/<rest>`                  -> BepInEx/config/<rest>  (no per-mod subfolder)
  - `[x/]plugins|patchers|monomod|core/<rest>` -> BepInEx/<that>/<Team-Package>/<rest>
  - `[x/]Name.mm.dll`                    -> BepInEx/monomod/<Team-Package>/Name.mm.dll
  - no trigger (or the trigger is the file itself): the FILE NAME alone ->
    BepInEx/plugins/<Team-Package>/<name> (sub-folders flattened)
so a normal mod's manifest.json / icon.png / README.md sit beside its DLLs in
BepInEx/plugins/<Team-Package>/, and a zip of loose sub-folders (MirageCore:
FSharp.Core/FSharp.Core.dll) lands flat as in a Gale profile. Two files
routed to one path (five LICENSE files): the last in zip order wins, as in
Gale (its extract overwrites); compared case-folded. Gale's per-game extra
subdirs (Valheim's `SlimVML` -> BepInEx/SlimVML/<Team-Package>/) are not
modelled: such files take the default route.

The framework package (the game's BepInExPack, e.g. Valheim's
denikson-BepInExPack_Valheim) is routed differently: its payload - the
shallowest folder in the zip that directly holds a `BepInEx/` folder (the
real Valheim pack nests it one level down, `BepInExPack_Valheim/`) - is
copied as-is to the tree ROOT (BepInEx/core, winhttp.dll, doorstop_config.ini,
doorstop_libs/, .doorstop_version, ...). The zip-root metadata files outside
that payload (manifest.json, icon.png, README.md, CHANGELOG.md) are not
copied; the load-order manifest records the framework's version instead.

Config files (anything routed under BepInEx/config/): since 0.6.51 every
install (fresh, update, reinstall, import, local zip) overwrites the config
files the package itself ships, edited or not - Gale's rule (its config
folder is untracked, ConflictResolution::Overwrite; user decision
2026-10-08), so a modpack installed last wins and an update brings its new
defaults. Config files no package ships (written by a mod at run time, made
by the user) are never touched. They are neither renamed by disable nor
deleted by removal (uninstall keeps them). install_package returns the
sha256 of every config it wrote; the load order's manifest keeps it per
entry ("config_sha256", 0.6.50) as a record only (0.6.50 used it to replace
only untouched configs).

Disable convention (BepInEx has no native one - its loader globs literally
`*.dll` under plugins/, THUNDERSTORE.md §2): every tracked non-config file of
a disabled mod is renamed `<name>` -> `<name>.disabled` (DISABLED_SUFFIX), so
nothing of it still matches `*.dll`; enable renames back. Same trick TMM uses
(`.old` there); the suffix is VOLT's own.
"""

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from .applog import log

BEPINEX_DIR = "BepInEx"
MANIFEST_FILE = "manifest.json"
DISABLED_SUFFIX = ".disabled"
CONFIG_FOLDER = "config"
ROUTES = ("plugins", "patchers", "monomod", "core", CONFIG_FOLDER)  # Gale's BepInEx subdirs, in its order
DEFAULT_ROUTE = "plugins"
MONOMOD_ROUTE = "monomod"
MONOMOD_SUFFIX = ".mm.dll"


class PackageError(ValueError):
    """A package that can't be installed. `kind` follows mods.py::scan_dir's
    problem vocabulary: "bad-zip" (not a readable zip / folder), "no-manifest"
    (no manifest.json at the root), "parse-error" (manifest.json isn't the
    expected JSON), "bad-path" (an entry that would escape the tree),
    "no-bepinex" (a framework package without a BepInEx/ folder)."""

    def __init__(self, kind: str, path, message: str):
        super().__init__(message)
        self.kind = kind
        self.path = str(path)
        self.message = message

    def problem(self) -> dict:
        return {"kind": self.kind, "path": self.path, "message": self.message}


def _clean_rel(name: str, source) -> str | None:
    """A zip/folder entry as a normalized posix path relative to the root, or
    None for a directory entry. PackageError("bad-path") when it would escape."""
    rel = name.replace("\\", "/")
    if rel.endswith("/"):
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts:
        return None
    if ".." in parts or rel.startswith("/") or (len(parts[0]) == 2 and parts[0][1] == ":"):
        raise PackageError("bad-path", source, f"Package entry escapes its folder: {name!r}")
    return "/".join(parts)


class PackageSource:
    """A package as a set of (relative posix path -> bytes): a .zip file (what
    the cache holds) or an already-extracted folder (a fixture, a local
    import). Use as a context manager."""

    def __init__(self, path):
        self.path = Path(path)
        self._zip: zipfile.ZipFile | None = None
        self._files: list[str] = []

    def __enter__(self) -> "PackageSource":
        if self.path.is_dir():
            for root, dirs, files in os.walk(self.path):
                dirs.sort()
                for f in sorted(files):
                    rel = _clean_rel(str(Path(root, f).relative_to(self.path)), self.path)
                    if rel:
                        self._files.append(rel)
            return self
        try:
            self._zip = zipfile.ZipFile(self.path)
        except (OSError, zipfile.BadZipFile) as err:
            raise PackageError("bad-zip", self.path, f"Not a readable package zip: {err}") from err
        seen = {}
        for info in self._zip.infolist():
            rel = _clean_rel(info.filename, self.path)
            if rel and not info.is_dir():
                seen[rel] = info.filename
        self._files = list(seen)
        self._names = seen
        return self

    def __exit__(self, *exc) -> None:
        if self._zip:
            self._zip.close()

    def files(self) -> list[str]:
        return list(self._files)

    def open(self, rel: str):
        if self._zip:
            return self._zip.open(self._names[rel])
        return open(self.path / rel, "rb")

    def read(self, rel: str) -> bytes:
        with self.open(rel) as f:
            return f.read()


def parse_manifest(data: bytes, source) -> dict:
    """manifest.json -> {name, version_number, description, website_url,
    dependencies: [str], author?}. PackageError("parse-error") when it isn't
    the documented shape."""
    try:
        m = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as err:
        raise PackageError("parse-error", source, f"manifest.json could not be parsed: {err}") from err
    if not isinstance(m, dict):
        raise PackageError("parse-error", source, "manifest.json is not a JSON object")
    name = m.get("name")
    version = m.get("version_number")
    if not isinstance(name, str) or not name.strip():
        raise PackageError("parse-error", source, "manifest.json has no name")
    if not isinstance(version, str) or not version.strip():
        raise PackageError("parse-error", source, "manifest.json has no version_number")
    deps = m.get("dependencies")
    out = {
        "name": name.strip(),
        "version_number": version.strip(),
        "description": m.get("description") if isinstance(m.get("description"), str) else "",
        "website_url": m.get("website_url") if isinstance(m.get("website_url"), str) else "",
        "dependencies": [d.strip() for d in deps if isinstance(d, str) and d.strip()] if isinstance(deps, list) else [],
    }
    if isinstance(m.get("author"), str):
        out["author"] = m["author"]
    return out


def read_manifest(source: PackageSource) -> dict:
    """The package's root manifest.json (case-insensitive name), parsed.
    PackageError("no-manifest") when there isn't one."""
    hit = next((f for f in source.files() if f.lower() == MANIFEST_FILE), None)
    if hit is None:
        raise PackageError("no-manifest", source.path, "No manifest.json at the package root - not a Thunderstore package")
    return parse_manifest(source.read(hit), source.path)


def _route_of(component: str) -> str | None:
    """The route a path component triggers: a route folder name (any case),
    or monomod for a name ending in `.mm.dll` (case as Gale matches it)."""
    low = component.lower()
    if low in ROUTES:
        return low
    return MONOMOD_ROUTE if component.endswith(MONOMOD_SUFFIX) else None


def route_file(rel: str, full_name: str) -> str:
    """Where one package file lands, relative to the tree root (posix);
    Gale's SubdirInstaller rule, the module docstring."""
    parts = rel.split("/")
    for i, part in enumerate(parts):
        route = _route_of(part)
        if route:
            break
    else:
        route = DEFAULT_ROUTE
    rest = parts[i + 1:] or parts[-1:]  # nothing after the trigger (or no trigger): the file name alone
    base = [BEPINEX_DIR, CONFIG_FOLDER] if route == CONFIG_FOLDER else [BEPINEX_DIR, route, full_name]
    return "/".join(base + rest)


def route_package(files: list[str], full_name: str) -> list[tuple[str, str]]:
    """[(source rel, destination rel)] for a normal (non-framework) package."""
    return [(f, route_file(f, full_name)) for f in files]


def framework_payload_root(files: list[str]) -> str:
    """The shallowest folder prefix ("" for the zip root, else "Sub/") that
    directly contains a BepInEx/ folder. PackageError("no-bepinex") if none."""
    best = None
    for f in files:
        parts = f.split("/")
        for i, p in enumerate(parts[:-1]):
            if p.lower() == BEPINEX_DIR.lower():
                prefix = "/".join(parts[:i])
                if best is None or prefix.count("/") + bool(prefix) < best.count("/") + bool(best):
                    best = prefix
                break
    if best is None:
        raise PackageError("no-bepinex", "", "Framework package has no BepInEx/ folder")
    return best + "/" if best else ""


def route_framework(files: list[str]) -> list[tuple[str, str]]:
    """[(source rel, destination rel)]: the payload folder's contents to the
    tree root; files outside it (zip-root manifest/icon/README) skipped."""
    root = framework_payload_root(files)
    return [(f, f[len(root):]) for f in files if f.startswith(root)]


def is_config_path(rel: str) -> bool:
    parts = rel.split("/")
    return len(parts) > 2 and parts[0].lower() == BEPINEX_DIR.lower() and parts[1].lower() == CONFIG_FOLDER


def _tree_path(tree_root: Path, rel: str) -> Path:
    if ".." in rel.split("/") or rel.startswith("/"):
        raise PackageError("bad-path", tree_root, f"Refusing to write outside the tree: {rel!r}")
    return tree_root.joinpath(*rel.split("/"))


def install_package(source_path, tree_root, full_name: str, framework: bool = False) -> dict:
    """Extracts one package into `tree_root` per the routing rules. Returns
    {"manifest": parsed manifest.json, "files": [tree-relative posix paths
    written, sorted], "config_sha256": {config path: sha256 of what this
    package wrote}}. Existing files are overwritten (a reinstall/update),
    config files included (0.6.51, the module docstring). PackageError
    for a malformed package; nothing is written before the manifest has been
    read and every path validated."""
    tree_root = Path(tree_root)
    with PackageSource(source_path) as src:
        manifest = read_manifest(src)
        files = src.files()
        routed = route_framework(files) if framework else route_package(files, full_name)
        # Flattening can send several files to one path (MirageCore's five LICENSE files): the last in
        # zip order wins, as in Gale (each extracted file overwrites); case-folded, as Windows sees paths.
        final: dict[str, list[str]] = {}
        for s, d in routed:
            final.setdefault(d.casefold(), [d, s])[1] = s
        # Validate every destination before touching the tree.
        dests = [(s, d, _tree_path(tree_root, d)) for d, s in final.values()]
        written, replaced, hashes = [], [], {}
        for rel, dest_rel, dest in dests:
            config = is_config_path(dest_rel)
            if config and dest.exists():
                replaced.append(dest_rel)  # Gale's rule: the package's own config wins, edited or not
            dest.parent.mkdir(parents=True, exist_ok=True)
            if config:
                data = src.read(rel)  # config files are small: hash what is written
                dest.write_bytes(data)
                hashes[dest_rel] = hashlib.sha256(data).hexdigest()
            else:
                with src.open(rel) as f_in, open(dest, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            written.append(dest_rel)
    written.sort()
    log(
        f"[bepinex] installed {full_name} {manifest['version_number']}{' (framework)' if framework else ''} "
        f"-> {tree_root}: {len(written)} files, {len(hashes)} config files written"
        + (f", {len(replaced)} existing config files overwritten {replaced[:20]}" if replaced else "")
    )
    return {"manifest": manifest, "files": written, "config_sha256": hashes}


def set_files_enabled(tree_root, files, enabled: bool) -> dict:
    """Renames each tracked non-config file between `<f>` and `<f>.disabled`.
    Idempotent. Returns {"renamed": n, "missing": [rel...]} - a file found
    under neither name (the tree drifted) is reported, not raised."""
    tree_root = Path(tree_root)
    renamed, missing = 0, []
    for rel in files:
        if is_config_path(rel):
            continue
        on = _tree_path(tree_root, rel)
        off = on.with_name(on.name + DISABLED_SUFFIX)
        src, dst = (off, on) if enabled else (on, off)
        if src.exists():
            os.replace(src, dst)
            renamed += 1
        elif not dst.exists():
            missing.append(rel)
    return {"renamed": renamed, "missing": missing}


def remove_files(tree_root, files) -> dict:
    """Deletes each tracked non-config file (enabled or disabled name) and
    prunes the emptied per-mod folders below BepInEx/<route>/. Config files
    stay. Returns {"removed": n, "skipped": [{"path", "error"}]}."""
    tree_root = Path(tree_root)
    removed, skipped, dirs = 0, [], set()
    for rel in files:
        if is_config_path(rel):
            continue
        on = _tree_path(tree_root, rel)
        for p in (on, on.with_name(on.name + DISABLED_SUFFIX)):
            try:
                p.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            except OSError as err:
                skipped.append({"path": str(p), "error": err.strerror or str(err)})
        dirs.add(on.parent)
    # Prune emptied folders, deepest first, never BepInEx/ or BepInEx/<route>/ themselves.
    for d in sorted(dirs, key=lambda p: len(p.parts), reverse=True):
        while d != tree_root and len(d.relative_to(tree_root).parts) > 2:
            try:
                d.rmdir()
            except OSError:
                break
            d = d.parent
    return {"removed": removed, "skipped": skipped}
