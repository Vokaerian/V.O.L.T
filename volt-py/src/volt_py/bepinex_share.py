"""Import/Export of a Thunderstore/BepInEx load order as a profile file
(THUNDERSTORE.md §4, stage 3e): r2modman / Thunderstore Mod Manager's own
`.r2z` format, so a VOLT export imports into TMM and a TMM export into VOLT.
Verified against a real TMM export (temp/Vinland_1790615256245.r2z) and
r2modman's own source (ProfileModList.createExport / ProfileUtils'
importer), 2026-09-29. Game-agnostic: the game's ThunderstoreGame supplies
the framework package name; nothing here is Valheim's.

The format - a plain deflate zip:
  export.r2x               YAML: profileName, mods: [{name: Team-Package,
                           version: {major, minor, patch}, enabled}]. The
                           framework pack is an ordinary entry; a disabled
                           mod is enabled: false.
  config/<path>            the profile's BepInEx/config/ tree, verbatim (TMM
                           writes backslash separators on Windows; either
                           separator is read here).
  <profile-relative path>  every other "config-like" file in the profile -
                           r2modman's rule: extension .cfg .txt .json .yml
                           .yaml .ini, minus manifest.json / mods.yml and
                           its own _state/ - e.g. a mod's translation .json
                           beside its DLL, doorstop_config.ini, changelog.txt.
  Mod files are never included: every package is re-downloaded on import.
r2modman's importer ignores YAML keys it doesn't know (its parser reads the
three named fields), so VOLT adds one top-level block, `volt: {app, game,
inactive: [Team-Package, ...]}`, to round-trip what .r2z can't express:
VOLT's Inactive list. TMM has one list with an on/off flag, so an inactive
mod exports as enabled: false (that's what TMM sees); a TMM file's
enabled: false comes back as an Active row switched off - the same
per-row switch TMM has - not as Inactive. `volt.game` (the APP-ROOT slug)
also tells a VOLT export made for another game apart.

Export writes the lists it's given (the screen's on-screen lists, unsaved
edits included - Copy to new's rule) or the saved manifest's. Import
builds a new load order, never merges: the framework at the
file's version, every listed package at the file's exact version - a
version Thunderstore no longer has falls back to the latest and is
reported as such, a package that can't be fetched at all is reported and
the rest still install, dependencies the file doesn't list come in at the
latest (bepinex_load_orders' policy) - then the archive's files are
restored into the tree (over the packages' default configs), then the
enabled flags and the volt inactive list are materialized with
save_load_order. The list order is the file's (cosmetic for BepInEx).
replace_profile (0.6.22, the screen's "Replace current profile") is that
same import under the file's profile name, then the replaced load order is
deleted - only when the import completed (nothing failed); otherwise the
new one is removed again and the old one is left as it was.

Share as code (the menus' "Export as code..." / "Import from code...")
is the same .r2z through Thunderstore's own profile-code service, the one
r2modman/TMM use (r2modman's src/r2mm/profiles/ProfilesClient.ts; probed
live 2026-09-29, no login needed): POST /api/experimental/legacyprofile/
create/ with Content-Type application/octet-stream and the body
"#r2modman\n" + base64(.r2z bytes) -> {"key": "<8-4-4-4-12 hex>"} (the
code; content-addressed, the same profile gives the same code); GET
/api/experimental/legacyprofile/get/<key>/ -> 302 to
ccdn.thunderstore.io/live/modpacks/legacyprofile/<key>, the same text
back (404 = expired / mistyped, 429 = rate limited). No server-side size
cap was hit at 12 MB; CODE_LIMIT is VOLT's own ceiling. A code import
downloads to <APP-ROOT>/cache/profiles/<key>.r2z and then runs the file
import unchanged.

Restore is allow-listed, never a blind unzip: an entry that would land
outside the load order's folder (.., absolute, a drive letter), an
executable under config/, anything outside config/ that isn't one of the
config-like extensions above, and a mod manager's own state files
(loadorder.json, mods.yml, export.r2x, _state/, BepInEx/cache/) are skipped
and listed. A file over FILE_LIMIT is skipped; an archive declaring more
than TOTAL_LIMIT bytes or ENTRY_LIMIT entries, a manifest over
MANIFEST_LIMIT, or an entry that inflates past its declared size, is
refused (zip bombs). Pure Python, no Qt; PyYAML through safe_load /
safe_dump only.
"""

import base64
import http.client
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import bepinex_install as bx
from . import bepinex_load_orders as lo
from . import thunderstore as ts
from .applog import clip, log

EXTENSION = ".r2z"
MANIFEST_NAME = "export.r2x"
CONFIG_FOLDER = "config"  # zip folder <-> BepInEx/config/
EXTRA_EXTENSIONS = frozenset({".cfg", ".txt", ".json", ".yml", ".yaml", ".ini"})  # r2modman's config-like set
SKIP_NAMES = frozenset({"manifest.json", "mods.yml", MANIFEST_NAME.lower(), lo.MANIFEST_FILE.lower()})
SKIP_FOLDERS = frozenset({"_state", "dotnet", "melonloader"})  # top-level: r2modman's own state / non-BepInEx loaders
BLOCKED_EXTENSIONS = frozenset({  # never restored under config/, whatever the file says
    ".dll", ".exe", ".bat", ".cmd", ".com", ".ps1", ".sh", ".msi", ".scr", ".vbs", ".js", ".jar",
    ".lnk", ".pif", ".cpl", ".so", ".dylib",
})
ENTRY_LIMIT = 20_000
FILE_LIMIT = 64 << 20
TOTAL_LIMIT = 512 << 20
MANIFEST_LIMIT = 4 << 20
VOLT_KEY = "volt"
FRAMEWORK_HINT = "bepinexpack"  # a package named like this that isn't the game's own = another game's profile
_CHUNK = 1 << 16
_DRIVE = re.compile(r"^[A-Za-z]:")
_BAD_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')

# ---- share as code (Thunderstore's legacyprofile service) ----
CODE_PREFIX = "#r2modman\n"
CODE_API = f"{ts.SITE}/api/experimental/legacyprofile"
CODE_LIMIT = 32 << 20  # zip bytes a code export accepts (VOLT's ceiling; the server took 12 MB in the probe)
CODE_TIMEOUT_S = 30.0
CODE_RETRIES = 5  # r2modman's: 5 tries, 1 s apart, never on a 404
CODE_RETRY_DELAY_S = 1.0
PROFILES_DIR = "profiles"  # <APP-ROOT>/cache/profiles/<key>.r2z - a downloaded code, kept like a package zip
_CODE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_sleep = time.sleep  # harness seam


class ProfileError(ValueError):
    """A profile file VOLT can't use; str() is a user-facing message."""


def _yaml():
    try:
        import yaml
    except ImportError as err:  # the dependency is declared; a venv that missed `uv sync` shouldn't crash the screen
        raise ProfileError("PyYAML isn't installed (run `uv sync` in volt-py/); .r2z profiles need it.") from err
    return yaml


def export_file_name(load_order_name: str) -> str:
    """The save dialog's default: the load order's name with the characters
    Windows forbids in a file name stripped, plus .r2z."""
    name = " ".join(_BAD_FILENAME.sub(" ", load_order_name or "").split()).strip(". ")
    return f"{name or 'profile'}{EXTENSION}"


# ---- zip entries -> where they go ----
def _norm_parts(name: str) -> list[str] | None:
    """A zip entry name as its path parts (either separator; empty / "."
    parts dropped); None for a directory entry."""
    rel = name.replace("\\", "/")
    if rel.endswith("/"):
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    return parts or None


def classify_entry(name: str) -> tuple[str | None, str]:
    """Where a profile zip entry lands in the load order's tree: (tree-
    relative posix path, "") or (None, why it's skipped). `config/<x>` ->
    `BepInEx/config/<x>` (executables blocked); any other path is restored
    as-is only when it's config-like and not a mod manager's own file."""
    parts = _norm_parts(name)
    if parts is None:
        return None, "folder"
    if ".." in parts or name.startswith(("/", "\\")) or _DRIVE.match(parts[0]):
        return None, "would land outside the profile folder"
    lower = [p.lower() for p in parts]
    ext = os.path.splitext(lower[-1])[1]
    if lower == [MANIFEST_NAME.lower()]:
        return None, "the profile manifest"
    if lower[-1] in SKIP_NAMES:
        return None, "a mod manager's own file"
    is_config = (lower[0] == CONFIG_FOLDER or (lower[0] == bx.BEPINEX_DIR.lower() and len(lower) > 2 and lower[1] == bx.CONFIG_FOLDER)) and len(parts) > 1
    if is_config:
        if ext in BLOCKED_EXTENSIONS:
            return None, "an executable file under config"
        rest = parts[1:] if lower[0] == CONFIG_FOLDER else parts[2:]
        return "/".join([bx.BEPINEX_DIR, bx.CONFIG_FOLDER, *rest]), ""
    if lower[0] in SKIP_FOLDERS:
        return None, "a mod manager's own state"
    if lower[0] == bx.BEPINEX_DIR.lower() and len(lower) > 1 and lower[1] == "cache":
        return None, "BepInEx's cache"
    if ext not in EXTRA_EXTENSIONS:
        return None, "not a config-like file (.cfg .txt .json .yml .yaml .ini)"
    return "/".join(parts), ""


def _dest_path(tree_root: Path, rel: str) -> Path:
    dest = tree_root.joinpath(*rel.split("/"))
    root_abs, dest_abs = os.path.abspath(tree_root), os.path.abspath(dest)
    if os.path.commonpath([root_abs, dest_abs]) != root_abs:  # classify_entry already refuses these; belt and braces
        raise ProfileError(f"Refusing to write outside the profile folder: {rel!r}")
    return dest


def _copy_limited(src, dst, limit: int, what: str) -> int:
    """copyfileobj with a hard cap: more than `limit` bytes = ProfileError
    (an entry inflating past its declared size, a zip bomb)."""
    total = 0
    while True:
        chunk = src.read(_CHUNK)
        if not chunk:
            return total
        total += len(chunk)
        if total > limit:
            raise ProfileError(f"{what} inflates past its declared size ({limit} bytes) - refusing it")
        dst.write(chunk)


class _Counter:
    def __init__(self):
        self.parts = []

    def write(self, b):
        self.parts.append(b)

    def value(self) -> bytes:
        return b"".join(self.parts)


def _read_limited(z: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    buf = _Counter()
    with z.open(info) as f:
        _copy_limited(f, buf, min(limit, info.file_size), info.filename)
    return buf.value()


def _extract_limited(z: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.part")
    try:
        with z.open(info) as f_in, open(tmp, "wb") as f_out:
            _copy_limited(f_in, f_out, info.file_size, info.filename)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


# ---- reading a profile ----
def _version_of(raw) -> str | None:
    """A mod entry's version: r2modman's {major, minor, patch} object, or a
    "1.2.3" string; None when it isn't either (the latest gets installed)."""
    if isinstance(raw, dict):
        nums = [raw.get(k) for k in ("major", "minor", "patch")]
        if all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in nums):
            return ".".join(str(n) for n in nums)
        return None
    if isinstance(raw, str) and ts.version_key(raw.strip()) != (-1,):
        return raw.strip()
    return None


def parse_manifest(data: bytes, source: str = MANIFEST_NAME) -> dict:
    """export.r2x -> {"name", "mods": [{full_name, namespace, name, version |
    None, enabled}], "inactive": [full_name...] (VOLT's block), "volt_game",
    "problems": [text]}. Tolerant like r2modman's own reader: unknown keys
    ignored, a missing `enabled` is True, an entry that isn't a package
    name / a version that isn't major.minor.patch / a duplicate is a
    problem line, not a refusal. ProfileError when it isn't a profile."""
    yaml = _yaml()
    try:
        doc = yaml.safe_load(data.decode("utf-8-sig"))
    except (yaml.YAMLError, UnicodeDecodeError) as err:
        raise ProfileError(f"{source} isn't valid YAML ({err}).") from err
    if not isinstance(doc, dict):
        raise ProfileError(f"{source} isn't a profile (expected profileName and a mods list).")
    name = doc.get("profileName")
    mods_raw = doc.get("mods")
    if mods_raw is None:
        mods_raw = []
    if not isinstance(mods_raw, list):
        raise ProfileError(f"{source}: `mods` isn't a list.")
    mods, problems, seen = [], [], set()
    for i, raw in enumerate(mods_raw, 1):
        if not isinstance(raw, dict):
            problems.append(f"Entry {i} isn't a mod entry ({clip(raw)}); skipped.")
            continue
        try:
            ref = ts.PackageRef.parse(raw.get("name"))
        except ValueError:
            problems.append(f"Entry {i}: {clip(raw.get('name'))!s} isn't a Thunderstore package name; skipped.")
            continue
        version = _version_of(raw.get("version")) or ref.version
        if raw.get("version") is not None and version is None:
            problems.append(f"{ref.full_name}: version {clip(raw.get('version'))} not understood; the latest will be installed.")
        if ref.full_name in seen:
            problems.append(f"{ref.full_name} is listed twice; the first entry counts.")
            continue
        seen.add(ref.full_name)
        mods.append({"full_name": ref.full_name, "namespace": ref.namespace, "name": ref.name,
                     "version": version, "enabled": raw.get("enabled") is not False})
    volt = doc.get(VOLT_KEY) if isinstance(doc.get(VOLT_KEY), dict) else {}
    raw_inactive = volt.get("inactive")
    inactive = [n for n in raw_inactive if isinstance(n, str) and n in seen] if isinstance(raw_inactive, list) else []
    return {
        "name": name.strip() if isinstance(name, str) else "",
        "mods": mods,
        "inactive": inactive,
        "volt_game": volt.get("game") if isinstance(volt.get("game"), str) else None,
        "problems": problems,
    }


def read_profile(path) -> dict:
    """Opens a .r2z: parse_manifest's dict plus "path", "files" [{entry, dest,
    size}] (what restore_files will write) and "skipped" [{entry, reason}].
    ProfileError for anything that isn't a usable profile (not a zip, no
    export.r2x, over the limits)."""
    path = Path(path)
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as err:
        raise ProfileError(f"{path.name} isn't a readable .r2z profile (a zip file): {err}") from err
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > ENTRY_LIMIT:
            raise ProfileError(f"{path.name} holds {len(infos)} files - more than a profile can ({ENTRY_LIMIT}); refusing it.")
        total = sum(i.file_size for i in infos)
        if total > TOTAL_LIMIT:
            raise ProfileError(f"{path.name} would unpack to {total >> 20} MB - more than a profile can ({TOTAL_LIMIT >> 20} MB); refusing it.")
        hit = next((i for i in infos if [p.lower() for p in (_norm_parts(i.filename) or [])] == [MANIFEST_NAME.lower()]), None)
        if hit is None:
            raise ProfileError(f"{path.name} has no {MANIFEST_NAME} inside - not an r2modman / VOLT profile.")
        if hit.file_size > MANIFEST_LIMIT:
            raise ProfileError(f"{path.name}: {MANIFEST_NAME} is {hit.file_size >> 20} MB - not a profile manifest; refusing it.")
        try:
            data = _read_limited(z, hit, MANIFEST_LIMIT)
        except (zipfile.BadZipFile, OSError, RuntimeError) as err:  # RuntimeError: an encrypted entry
            raise ProfileError(f"{path.name}: couldn't read {MANIFEST_NAME}: {err}") from err
    profile = parse_manifest(data, f"{path.name}: {MANIFEST_NAME}")
    files, skipped = [], []
    for i in infos:
        dest, reason = classify_entry(i.filename)
        if dest is None:
            if reason not in ("folder", "the profile manifest"):
                skipped.append({"entry": i.filename, "reason": reason})
        elif i.file_size > FILE_LIMIT:
            skipped.append({"entry": i.filename, "reason": f"bigger than {FILE_LIMIT >> 20} MB"})
        else:
            files.append({"entry": i.filename, "dest": dest, "size": i.file_size})
    profile.update({"path": str(path), "files": files, "skipped": skipped})
    log(f"[share] read {path}: {profile['name']!r}, {len(profile['mods'])} mods, {len(files)} files to restore, "
        f"{len(skipped)} skipped, {len(profile['problems'])} problems")
    return profile


def framework_entry(profile: dict, game: lo.ThunderstoreGame) -> dict | None:
    """The file's entry for this game's framework package, if listed."""
    return next((m for m in profile["mods"] if m["full_name"] == game.framework_package), None)


def check_game(profile: dict, game: lo.ThunderstoreGame, game_name: str | None = None) -> None:
    """ProfileError when the file was made for another game: a VOLT export's
    `volt.game` isn't this game's slug, or the file uses a different
    community's BepInEx pack (a package named BepInExPack* that isn't this
    game's framework_package - every Thunderstore community's pack is named
    that way)."""
    game_name = game_name or game.slug
    if profile.get("volt_game") and profile["volt_game"] != game.slug:
        raise ProfileError(f"This profile was exported for another game ({profile['volt_game']}), not {game_name}.")
    foreign = [m["full_name"] for m in profile["mods"]
               if m["name"].lower().startswith(FRAMEWORK_HINT) and m["full_name"] != game.framework_package]
    if foreign:
        raise ProfileError(
            f"This profile is for a different game: it uses {foreign[0]} as its BepInEx pack; "
            f"{game_name}'s is {game.framework_package}."
        )


# ---- export ----
def export_files(tree_root) -> list[tuple[str, Path]]:
    """[(zip entry name, file)]: BepInEx/config/** as config/**, then the
    rest of the tree's config-like files (r2modman's rule, module docstring)
    at their tree-relative paths; loadorder.json, manifest.json, .disabled
    files, BepInEx/cache and symlinks left out. Sorted, deterministic."""
    root = Path(tree_root)
    out: list[tuple[str, Path]] = []
    config = root / bx.BEPINEX_DIR / bx.CONFIG_FOLDER
    if config.is_dir():
        for dirpath, dirnames, filenames in os.walk(config):
            dirnames.sort()
            for f in sorted(filenames):
                p = Path(dirpath, f)
                if not p.is_symlink():
                    out.append((f"{CONFIG_FOLDER}/{p.relative_to(config).as_posix()}", p))
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        keep = []
        for d in sorted(dirnames):
            dl = d.lower()
            if rel_dir == "." and dl in SKIP_FOLDERS:
                continue
            if rel_dir.lower() == bx.BEPINEX_DIR.lower() and dl in (bx.CONFIG_FOLDER, "cache"):
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            fl = f.lower()
            if os.path.splitext(fl)[1] not in EXTRA_EXTENSIONS or fl in SKIP_NAMES:
                continue
            p = Path(dirpath, f)
            if not p.is_symlink():
                out.append((p.relative_to(root).as_posix(), p))
    return out


def _mod_entry(full_name: str, version: str, enabled: bool) -> dict:
    key = ts.version_key(version)
    if key == (-1,):
        log(f"[share] {full_name}: version {version!r} isn't major.minor.patch; exported as 0.0.0")
        key = (0, 0, 0)
    return {"name": full_name, "version": {"major": key[0], "minor": key[1], "patch": key[2]}, "enabled": bool(enabled)}


def build_manifest(manifest: dict, game: lo.ThunderstoreGame, *, active=None, inactive=None, app_version=None) -> dict:
    """The export.r2x document for a load order: the framework first, then
    Active in order (enabled = the toggle), then Inactive as enabled: false,
    plus VOLT's `volt` block. `active` / `inactive` (save_load_order's
    argument shapes) override the manifest's own lists - the screen passes
    its on-screen lists; both None = the saved lists. ValueError for a
    listed mod that isn't installed."""
    have = lo.installed(manifest)
    fw = manifest.get("framework")
    fw_name = fw["full_name"] if fw else None
    if active is None and inactive is None:
        act = [(e["full_name"], e["enabled"]) for e in manifest["active"]]
        ina = [e["full_name"] for e in manifest["inactive"]]
    else:
        act, ina = [], []
        for item in active or []:
            name, enabled = (item.get("full_name"), item.get("enabled", True)) if isinstance(item, dict) else (item, True)
            if name == fw_name:
                raise ValueError(f"{name} is the framework package: pinned, not part of the lists")
            if name not in have:
                raise ValueError(f"{name!r} is not installed in this profile")
            act.append((name, bool(enabled)))
        for name in inactive or []:
            if name == fw_name or name not in have:
                raise ValueError(f"{name!r} is not installed in this profile")
            ina.append(name)
    mods = []
    if fw:
        mods.append(_mod_entry(fw["full_name"], fw["version"], True))
    mods += [_mod_entry(n, have[n]["version"], en) for n, en in act]
    mods += [_mod_entry(n, have[n]["version"], False) for n in ina]
    return {
        "profileName": manifest["name"],
        "mods": mods,
        VOLT_KEY: {"app": app_version or "", "game": game.slug, "inactive": list(ina)},
    }


def dump_manifest(doc: dict) -> str:
    """The YAML text r2modman reads (block style, key order kept)."""
    return _yaml().safe_dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def dependency_strings(manifest: dict, active) -> dict:
    """Export... > Dependency strings... (THUNDERSTORE.md §8d): one
    `"Team-Package-Version",` line per mod a modpack's manifest.json
    `dependencies` array would list - the pinned framework first, then each
    Active mod that is switched on, in `active`'s order (save_load_order's
    argument shape: the screen's on-screen list, unsaved edits included).
    Switched-off Active mods and the Inactive list are left out, and so is
    a local import (online_source: false - no Thunderstore identity to
    depend on) or an entry without a major.minor.patch version, counted
    instead. Returns {"lines", "local", "invalid"}."""
    have = lo.installed(manifest)
    fw = manifest.get("framework")
    picked = [fw] if fw else []
    for item in active:
        name, enabled = (item.get("full_name"), item.get("enabled", True)) if isinstance(item, dict) else (item, True)
        if enabled and name in have and have[name] is not fw:
            picked.append(have[name])
    lines, local, invalid = [], 0, 0
    for e in picked:
        if not e.get("online_source", True):
            local += 1
            continue
        try:
            lines.append(f'"{ts.PackageRef(e["namespace"], e["name"], e["version"]).key}",')
        except ValueError:
            log(f"[share] dependency strings: {e['full_name']} has no usable version ({e.get('version')!r}); left out")
            invalid += 1
    return {"lines": lines, "local": local, "invalid": invalid}


def build_profile_zip(app_root, slug, game: lo.ThunderstoreGame, out, *, active=None, inactive=None, app_version=None) -> dict:
    """Writes the load order's .r2z into `out` (a path or a binary file
    object). Returns {"mods", "files", "config_files"}. ValueError /
    OSError / ProfileError propagate."""
    manifest = lo.load_load_order(app_root, slug)
    doc = build_manifest(manifest, game, active=active, inactive=inactive, app_version=app_version)
    text = dump_manifest(doc)
    entries = export_files(lo.tree_root(app_root, slug))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST_NAME, text)
        for arc, p in entries:
            z.write(p, arc)
    config_files = sum(1 for arc, _ in entries if arc.startswith(f"{CONFIG_FOLDER}/"))
    return {"mods": len(doc["mods"]), "files": len(entries), "config_files": config_files}


def export_profile(app_root, slug, game: lo.ThunderstoreGame, dest, *, active=None, inactive=None, app_version=None) -> dict:
    """Writes the load order as `dest` (a .r2z; temp sibling + os.replace).
    Returns {"path", "mods", "files", "config_files"}. ValueError /
    OSError / ProfileError propagate."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.part")
    try:
        res = build_profile_zip(app_root, slug, game, tmp, active=active, inactive=inactive, app_version=app_version)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    log(f"[share] exported {slug} -> {dest}: {res['mods']} mods, {res['files']} files ({res['config_files']} config), "
        f"{dest.stat().st_size} bytes")
    return {"path": dest, **res}


# ---- share as code ----
def parse_code(text) -> str:
    """The profile code out of whatever was pasted: the 8-4-4-4-12 hex key,
    lowercased - surrounding whitespace / newlines / quotes, or the whole
    .../legacyprofile/get/<key>/ URL, are fine. ValueError otherwise."""
    m = _CODE.search(text if isinstance(text, str) else "")
    if not m:
        raise ValueError(f"Not a profile code (expected 8-4-4-4-12 hex characters, like 01a0eadb-df03-ee4a-20f7-eccc823a5a5d): {(text or '').strip()[:60]!r}")
    return m.group(0).lower()


def encode_code_payload(zip_bytes: bytes) -> bytes:
    return CODE_PREFIX.encode("ascii") + base64.b64encode(zip_bytes)


def decode_code_payload(data: bytes) -> bytes:
    """The .r2z bytes out of a downloaded code payload; ProfileError when it
    isn't r2modman's "#r2modman\n<base64>" text."""
    text = data.decode("utf-8-sig", errors="replace").lstrip()
    if not text.startswith(CODE_PREFIX.rstrip("\n")):
        raise ProfileError("Thunderstore sent something that isn't a profile code's data (no #r2modman header).")
    body = "".join(text[len(CODE_PREFIX.rstrip("\n")):].split())
    try:
        return base64.b64decode(body, validate=True)
    except (ValueError, TypeError) as err:  # binascii.Error is a ValueError
        raise ProfileError(f"The profile code's data is damaged (bad base64: {err}).") from err


def _code_request(url: str, app_version=None, data: bytes | None = None) -> urllib.request.Request:
    headers = {"User-Agent": f"VOLT/{app_version or '?'} Thunderstore client", "Accept": "*/*"}
    if data is not None:
        headers["Content-Type"] = "application/octet-stream"
    return urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")


def upload_code(zip_bytes: bytes, app_version=None) -> str:
    """POSTs a .r2z to Thunderstore's profile service; returns the code.
    ProfileError (too big, rate limited, HTTP / network failure)."""
    if len(zip_bytes) > CODE_LIMIT:
        raise ProfileError(f"This profile is {len(zip_bytes) >> 20} MB - more than a shareable code can carry "
                           f"({CODE_LIMIT >> 20} MB). Export to a file instead.")
    url = f"{CODE_API}/create/"
    payload = encode_code_payload(zip_bytes)
    log(f"[share] POST {url} ({len(payload)} bytes payload, {len(zip_bytes)} zip bytes)")
    try:
        with ts.env.urlopen(_code_request(url, app_version, payload), timeout=CODE_TIMEOUT_S) as res:
            status, body = getattr(res, "status", 200), res.read()
    except urllib.error.HTTPError as err:
        log(f"[share] upload: HTTP {err.code}")
        if err.code == 413:
            raise ProfileError("Thunderstore refused the profile as too large. Export to a file instead.") from err
        if err.code == 429:
            raise ProfileError("Thunderstore is rate-limiting profile uploads right now - try again in a minute.") from err
        raise ProfileError(f"Thunderstore returned HTTP {err.code} uploading the profile.") from err
    except (OSError, http.client.HTTPException) as err:
        log(f"[share] upload failed: {err!r}")
        raise ProfileError(f"Couldn't reach Thunderstore ({getattr(err, 'reason', None) or err}). Check your internet connection.") from err
    try:
        key = json.loads(body.decode("utf-8-sig", errors="replace")).get("key") if 200 <= status < 300 else None
    except (ValueError, AttributeError):
        key = None
    if not isinstance(key, str) or not _CODE.fullmatch(key):
        log(f"[share] upload: unexpected reply HTTP {status}: {clip(body[:200])}")
        raise ProfileError("Thunderstore sent an unexpected reply to the profile upload.")
    log(f"[share] uploaded: code {key}")
    return key.lower()


def download_code(key: str, app_version=None, retries: int = CODE_RETRIES) -> bytes:
    """GETs a profile code's .r2z bytes (the redirect to the CDN followed).
    A 404 is final ("no such code"); anything else is retried r2modman's
    way (CODE_RETRIES tries, CODE_RETRY_DELAY_S apart). ProfileError."""
    key = parse_code(key)
    url = f"{CODE_API}/get/{key}/"
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        log(f"[share] GET {url} (try {attempt} of {retries})")
        try:
            with ts.env.urlopen(_code_request(url, app_version), timeout=CODE_TIMEOUT_S) as res:
                status = getattr(res, "status", 200)
                buf = _Counter()
                _copy_limited(res, buf, CODE_LIMIT * 2, "the profile code's data")
                data = buf.value()
            if not 200 <= status < 300:
                raise ProfileError(f"Thunderstore returned HTTP {status} for the profile code.")
            log(f"[share] downloaded code {key}: {len(data)} bytes")
            return decode_code_payload(data)
        except urllib.error.HTTPError as err:
            log(f"[share] code {key}: HTTP {err.code}")
            if err.code == 404:
                raise ProfileError(f"Thunderstore has no profile for the code {key} - it may have expired, or a character is off.") from err
            last = ProfileError("Thunderstore is rate-limiting profile downloads right now - try again in a minute." if err.code == 429
                                else f"Thunderstore returned HTTP {err.code} for the profile code.")
        except (OSError, http.client.HTTPException) as err:
            log(f"[share] code {key}: request failed: {err!r}")
            last = ProfileError(f"Couldn't reach Thunderstore ({getattr(err, 'reason', None) or err}). Check your internet connection.")
        if attempt < retries:
            _sleep(CODE_RETRY_DELAY_S)
    assert last is not None
    raise last


def export_code(app_root, slug, game: lo.ThunderstoreGame, *, active=None, inactive=None, app_version=None) -> dict:
    """The load order as a profile code: build_profile_zip in memory, then
    upload_code. Returns {"code", "mods", "files", "config_files", "bytes"}."""
    buf = io.BytesIO()
    res = build_profile_zip(app_root, slug, game, buf, active=active, inactive=inactive, app_version=app_version)
    data = buf.getvalue()
    code = upload_code(data, app_version)
    log(f"[share] exported {slug} as code {code}: {res['mods']} mods, {res['files']} files, {len(data)} bytes")
    return {"code": code, **res, "bytes": len(data)}


def code_profile_path(app_root, key: str) -> Path:
    return Path(app_root) / ts.CACHE_DIR / PROFILES_DIR / f"{parse_code(key)}{EXTENSION}"


def fetch_code_profile(app_root, key: str, app_version=None) -> dict:
    """Downloads a profile code into <APP-ROOT>/cache/profiles/<key>.r2z and
    reads it (read_profile's dict, "path" = that file, "source" = the
    code). The screen then runs the same import as for a picked file."""
    key = parse_code(key)
    data = download_code(key, app_version)
    path = code_profile_path(app_root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.part")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    profile = read_profile(path)
    profile["source"] = f"code {key}"
    return profile


# ---- import ----
def restore_files(zip_path, tree_root) -> dict:
    """Extracts a profile's restorable entries (classify_entry) into the
    tree, overwriting what's there (the file's config beats a package's
    default). Returns {"restored": [tree-relative...], "skipped": [{entry,
    reason}]}; one bad entry never stops the rest."""
    tree_root = Path(tree_root)
    restored, skipped = [], []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            dest_rel, reason = classify_entry(info.filename)
            if dest_rel is None:
                if reason not in ("folder", "the profile manifest"):
                    skipped.append({"entry": info.filename, "reason": reason})
                continue
            if info.file_size > FILE_LIMIT:
                skipped.append({"entry": info.filename, "reason": f"bigger than {FILE_LIMIT >> 20} MB"})
                continue
            try:
                _extract_limited(z, info, _dest_path(tree_root, dest_rel))
            except (OSError, ProfileError, zipfile.BadZipFile, RuntimeError) as err:
                skipped.append({"entry": info.filename, "reason": str(err)})
                continue
            restored.append(dest_rel)
    log(f"[share] restored {len(restored)} files into {tree_root}, {len(skipped)} skipped: {clip([s['entry'] for s in skipped])}")
    return {"restored": restored, "skipped": skipped}


def import_profile(app_root, path, name: str, game: lo.ThunderstoreGame, app_version=None, *,
                   progress=None, game_name: str | None = None, source: str | None = None) -> dict:
    """The whole import (module docstring), as one job: a NEW load order
    called `name`. `progress(text)` gets one line per step; `source` is
    what the summary says the load order came from (default: the file
    name; a code import passes "code <key>"). Returns the summary {slug,
    name, profile_name, path, source, manifest, listed, framework: {wanted,
    installed, fell_back}, installed (listed packages that landed), extra
    (dependencies the file didn't list), fallbacks [{package, wanted,
    installed}], failed [{package, message}], disabled (Active, switched
    off), inactive, restored [paths], skipped [{entry, reason}], problems
    (manifest oddities), errors (a restore / save step that failed)}.
    ProfileError (not a usable profile, another game's) and a failed
    framework install (ThunderstoreError etc. - nothing is left behind)
    propagate; everything after the framework is reported, not raised."""
    report = progress or (lambda text: None)
    profile = read_profile(path)
    check_game(profile, game, game_name)
    fw_mod = framework_entry(profile, game)
    fw_wanted = fw_mod["version"] if fw_mod else None
    report(f"Installing {game.framework_package}{' ' + fw_wanted if fw_wanted else ''}...")
    manifest = lo.create_load_order(app_root, name, game, app_version, framework_version=fw_wanted)
    slug = manifest["slug"]
    fw_got = manifest["framework"]["version"]
    summary = {
        "slug": slug, "name": manifest["name"], "profile_name": profile["name"], "path": str(path),
        "source": source or Path(path).name,
        "framework": {"wanted": fw_wanted, "installed": fw_got, "fell_back": bool(fw_wanted) and fw_wanted != fw_got},
        "installed": [], "extra": [], "fallbacks": [], "failed": [], "disabled": [], "inactive": [],
        "restored": [], "skipped": list(profile["skipped"]), "problems": list(profile["problems"]), "errors": [],
    }
    listed = [m for m in profile["mods"] if m["full_name"] != game.framework_package]
    listed_names = {m["full_name"] for m in listed}
    pins = {m["full_name"]: m["version"] for m in listed if m["version"]}
    n = summary["listed"] = len(listed)
    for i, m in enumerate(listed, 1):
        report(f"Installing {m['full_name']}{' ' + m['version'] if m['version'] else ''} ({i} of {n})...")
        try:
            res = lo.install_mod(app_root, slug, game, ts.PackageRef(m["namespace"], m["name"], m["version"]), app_version,
                                 pins=pins, fallback_latest=True)
        except (ts.ThunderstoreError, bx.PackageError, OSError, ValueError) as err:
            log(f"[share] import {slug}: {m['full_name']} failed: {err!r}")
            summary["failed"].append({"package": m["full_name"], "message": str(err)})
            continue
        for e in res["installed"]:
            (summary["installed"] if e["full_name"] in listed_names else summary["extra"]).append(e["full_name"])
        summary["fallbacks"] += res["fallbacks"]
        summary["failed"] += [{"package": p.get("package", "?"), "message": p.get("message", "")} for p in res["problems"]]
    failed, seen_failed = [], set()
    for f in summary["failed"]:  # a dependency that failed once and then failed as its own entry: one line, the first message
        if f["package"] not in seen_failed and f["package"] not in summary["installed"]:
            seen_failed.add(f["package"])
            failed.append(f)
    summary["failed"] = failed
    report("Restoring config files...")
    root = lo.tree_root(app_root, slug)
    try:
        res = restore_files(path, root)
        summary["restored"], summary["skipped"] = res["restored"], res["skipped"]  # the same classification read_profile made
    except (OSError, ProfileError, zipfile.BadZipFile) as err:
        log(f"[share] import {slug}: restoring files failed: {err!r}")
        summary["errors"].append(f"Config files couldn't be restored: {err}")
    report("Applying the on/off flags...")
    manifest = lo.load_load_order(app_root, slug)
    have = lo.installed(manifest)
    flags = {m["full_name"]: m["enabled"] for m in listed}
    inactive_set = {x for x in profile["inactive"] if x in have and x != game.framework_package}
    order = [m["full_name"] for m in listed if m["full_name"] in have]
    order += [e["full_name"] for e in manifest["active"] if e["full_name"] not in listed_names]
    active = [{"full_name": x, "enabled": flags.get(x, True)} for x in order if x not in inactive_set]
    inactive = [x for x in order if x in inactive_set]
    try:
        manifest = lo.save_load_order(app_root, slug, active, inactive)
    except (OSError, ValueError) as err:
        log(f"[share] import {slug}: applying flags failed: {err!r}")
        summary["errors"].append(f"The on/off flags couldn't be applied: {err}")
    summary["disabled"] = [a["full_name"] for a in active if not a["enabled"]]
    summary["inactive"] = inactive
    summary["manifest"] = manifest
    log(f"[share] imported {path} -> {slug} ({manifest['name']!r}): {len(summary['installed'])} of {n} listed installed, "
        f"{len(summary['extra'])} extra, {len(summary['fallbacks'])} fallbacks, {len(summary['failed'])} failed, "
        f"{len(summary['disabled'])} off, {len(inactive)} inactive, {len(summary['restored'])} files restored, "
        f"{len(summary['skipped'])} skipped, {len(summary['errors'])} errors")
    return summary


def replace_profile(app_root, path, old_slug, game: lo.ThunderstoreGame, app_version=None, *,
                    progress=None, game_name: str | None = None, source: str | None = None) -> dict:
    """Replace the load order `old_slug` with the profile at `path`: a full
    import_profile into a NEW load order named as the file says (its
    profileName, else the file stem; _allocate gives a clashing name a
    fresh folder - the old one's included, it still exists then). A
    framework failure or unexpected error removes whatever was created and
    propagates, `old_slug` untouched. A complete import is finished at once
    (finish_replace(keep_new=True)). An incomplete one (failed mods /
    errors) comes back with "partial": True and BOTH load orders still on
    disk: the caller asks (GUI thread) and calls finish_replace."""
    old = lo.load_load_order(app_root, old_slug)  # validates the slug; unreadable = refused before anything is built
    profile = read_profile(path)
    name = profile["name"] or Path(path).stem
    before = {o["slug"] for o in lo.list_load_orders(app_root)}
    try:
        summary = import_profile(app_root, path, name, game, app_version, progress=progress, game_name=game_name, source=source)
    except Exception as err:
        log(f"[share] replace {old_slug}: import failed ({err!r}); new load order removed, {old_slug} kept")
        for o in lo.list_load_orders(app_root):  # whatever this import created (one job at a time: the screen is busy)
            if o["slug"] not in before:
                lo.delete_load_order(app_root, o["slug"])
        raise
    summary["old_slug"], summary["old_name"] = old_slug, old["name"]
    if summary["failed"] or summary["errors"]:
        summary["partial"] = True
        log(f"[share] replace {old_slug}: import incomplete ({len(summary['failed'])} failed, {len(summary['errors'])} errors); "
            f"{summary['slug']} built, {old_slug} kept until decided")
        return summary
    return finish_replace(app_root, summary, keep_new=True)


def finish_replace(app_root, summary: dict, *, keep_new: bool) -> dict:
    """keep_new: delete the old load order, then reclaim_slug the new one
    (a same-name replace ends in the clean folder); the summary gains
    "replaced" + "replace_skipped" and the final "slug" / "manifest".
    Not keep_new: the new load order is deleted, the old one untouched, and
    ProfileError (replace_kept_text) is raised."""
    old_slug, old_name, new_slug = summary["old_slug"], summary["old_name"], summary["slug"]
    summary["partial"] = False
    if not keep_new:
        lo.delete_load_order(app_root, new_slug)
        log(f"[share] replace {old_slug}: kept; {new_slug} removed")
        raise ProfileError(replace_kept_text(summary))
    res = lo.delete_load_order(app_root, old_slug)
    summary["replaced"], summary["replace_skipped"] = old_name, res.get("skipped", [])
    summary["slug"] = lo.reclaim_slug(app_root, new_slug)
    summary["manifest"] = lo.load_load_order(app_root, summary["slug"])
    log(f"[share] replaced {old_slug} ({old_name!r}) with {summary['slug']} ({summary['name']!r}"
        f"{', built as ' + new_slug if new_slug != summary['slug'] else ''}); {len(summary['failed'])} failed, "
        f"{len(summary['replace_skipped'])} files of the old one left behind")
    return summary


def failed_lines(summary: dict, cap: int = 8) -> list[str]:
    """One line per failed mod / error, the first `cap`, then "and N more"."""
    items = [f"  - {f['package']}: {f['message']}" for f in summary["failed"]] + [f"  - {e}" for e in summary["errors"]]
    return items[:cap] + ([f"  ... and {len(items) - cap} more"] if len(items) > cap else [])


def replace_kept_text(summary: dict) -> str:
    old = summary["old_name"]
    return "\n".join([f'"{old}" wasn\'t replaced: the import didn\'t complete, so it was undone and "{old}" is unchanged.',
                      ""] + failed_lines(summary) + ["", 'To keep what did install, import again and choose "Add as a new profile".'])


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def describe_import(summary: dict) -> str:
    """The import's summary dialog text: what landed, what fell back to the
    latest, what failed, what was restored / skipped."""
    total = summary["listed"]
    lines = [f'Imported "{summary["name"]}" from {summary.get("source") or Path(summary["path"]).name}.', ""]
    if summary.get("replaced"):
        lines[1:1] = [f'It replaced the profile "{summary["replaced"]}".']
        if summary.get("replace_skipped"):
            lines[2:2] = [f'{_plural(len(summary["replace_skipped"]), "file")} of "{summary["replaced"]}" couldn\'t be '
                          "removed (in use?) and were left in its folder."]
    fw = summary["framework"]
    fw_line = f"Framework: {fw['installed']}"
    if fw["fell_back"]:
        fw_line += f" (the file's {fw['wanted']} is no longer on Thunderstore; the latest was installed instead)"
    elif not fw["wanted"]:
        fw_line += " (the file doesn't list the framework; the latest was installed)"
    lines.append(fw_line)
    got = len(summary["installed"])
    line = f"Mods installed: {got} of {total}"
    if summary["extra"]:
        line += f", plus {_plural(len(summary['extra']), 'dependency', 'dependencies')} the file doesn't list ({', '.join(summary['extra'])})"
    lines.append(line + ".")
    if summary["disabled"]:
        lines.append(f"Switched off, as in the file: {', '.join(summary['disabled'])}.")
    if summary["inactive"]:
        lines.append(f"Inactive, as in the file: {', '.join(summary['inactive'])}.")
    if summary["fallbacks"]:
        lines += ["", f"{_plural(len(summary['fallbacks']), 'mod')} at the latest version instead of the file's (that version is no longer on Thunderstore):"]
        lines += [f"  - {f['package']}: wanted {f['wanted']}, installed {f['installed']}" for f in summary["fallbacks"]]
    if summary["failed"]:
        lines += ["", f"{_plural(len(summary['failed']), 'mod')} couldn't be installed:"]
        lines += [f"  - {f['package']}: {f['message']}" for f in summary["failed"]]
    lines.append("")
    files = f"Config files restored: {len(summary['restored'])}"
    if summary["skipped"]:
        files += f" ({_plural(len(summary['skipped']), 'file')} in the archive skipped - not config files, or unsafe to restore)"
    lines.append(files + ".")
    if summary["problems"]:
        lines += ["", "Oddities in the file:"] + [f"  - {p}" for p in summary["problems"]]
    if summary["errors"]:
        lines += ["", "Problems:"] + [f"  - {e}" for e in summary["errors"]]
    return "\n".join(lines)
