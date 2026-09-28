"""Path autodetection (port of Electron's src/electron/lib/paths.js).

Finds the RimWorld install root for Steam or GOG, plus the game's config
folder (ModsConfig.xml). Both storefronts use the same <install root>/Mods
layout, so this only branches to *find* the root.
"""

import os
import re
import sys
from pathlib import Path

from .fsutil import exists, find_child_ci, is_dir, read_text
from .registry import read_reg_tree, read_reg_value
from .vdf import get_ci, parse_vdf

STEAM_APPID = "294100"
GOG_GAME_ID = "1094900708"  # RimWorld's GOG product id; the gameName match is the primary check.
GAME_EXES = ["RimWorldWin64.exe", "RimWorldWin.exe", "RimWorldLinux", "RimWorldMac.app"]

_WIN = sys.platform == "win32"


def norm(p):
    """Normalize a path string (registry values sometimes use forward
    slashes - Steam's SteamPath does). Falsy input is returned unchanged."""
    return Path(os.path.normpath(p)) if p else p


def _key(p) -> str:
    return str(p).lower() if _WIN else str(p)


def dedupe(paths):
    """Drop falsy entries and duplicates (case-insensitively on Windows),
    keeping first-seen order."""
    seen = set()
    out = []
    for p in paths:
        if not p or _key(p) in seen:
            continue
        seen.add(_key(p))
        out.append(p)
    return out


def is_game_root(dir) -> bool:
    if not is_dir(dir):
        return False
    d = Path(dir)
    if is_dir(d / "Data" / "Core"):
        return True
    return any(exists(d / exe) for exe in GAME_EXES)


def find_game_exe(game_dir) -> Path | None:
    """The first GAME_EXES entry that exists directly in `game_dir`, else None
    (main.js game:launch's lookup)."""
    if not game_dir:
        return None
    for name in GAME_EXES:
        exe = Path(game_dir) / name
        if exists(exe):
            return exe
    return None


def open_path(path) -> None:
    """Opens `path` with the OS's own association, like double-clicking it in
    Explorer (Electron's shell.openPath). Returns once the OS has started it;
    raises OSError carrying the OS's own reason if it refuses."""
    startfile = getattr(os, "startfile", None)  # Windows-only
    if startfile is None:
        # ponytail: Windows-first (CLAUDE.md §3); Linux/Mac launch comes with
        # their packaging (xdg-open / `open`).
        raise OSError(f"Launching isn't supported on {sys.platform} yet: {path}")
    startfile(str(path))


def normalize_game_dir(dir) -> Path | None:
    """Accepts the install root, or its Mods/Data folder picked by mistake."""
    if not dir:
        return None
    # abspath, not Path.resolve(): Node's path.resolve doesn't follow symlinks.
    d = Path(os.path.abspath(dir))
    if is_game_root(d):
        return d
    parent = d.parent
    if parent != d and d.name.lower() in ("mods", "data") and is_game_root(parent):
        return parent
    return None


def steam_root_candidates() -> list[Path]:
    c = []
    home = Path.home()
    if sys.platform == "win32":
        c.append(read_reg_value("HKCU\\Software\\Valve\\Steam", "SteamPath"))
        c.append(read_reg_value("HKLM\\SOFTWARE\\WOW6432Node\\Valve\\Steam", "InstallPath"))
        c.append(read_reg_value("HKLM\\SOFTWARE\\Valve\\Steam", "InstallPath"))
        c += ["C:\\Program Files (x86)\\Steam", "C:\\Program Files\\Steam"]
    elif sys.platform == "linux":
        c += [
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
        ]
    elif sys.platform == "darwin":
        c.append(home / "Library" / "Application Support" / "Steam")
    return dedupe(norm(p) for p in c)


def steam_libraries(steam_root) -> list[dict]:
    """Library folders from libraryfolders.vdf. has_app: True/False when the
    file lists installed app ids (newer format), None when unknown (older)."""
    steam_root = Path(steam_root)
    libs = [{"path": steam_root, "has_app": None}]
    for rel in (("steamapps", "libraryfolders.vdf"), ("config", "libraryfolders.vdf")):
        try:
            data = parse_vdf(read_text(steam_root.joinpath(*rel)))
        except (OSError, ValueError):
            continue
        root = get_ci(data, "libraryfolders")
        if not isinstance(root, dict):
            continue
        for k, v in root.items():
            if not re.fullmatch(r"\d+", k, re.ASCII):
                continue
            p = v if isinstance(v, str) else get_ci(v, "path")
            if not p:
                continue
            apps = get_ci(v, "apps") if isinstance(v, dict) else None
            has_app = (STEAM_APPID in apps) if isinstance(apps, dict) else None
            libs.append({"path": norm(p), "has_app": has_app})
    # Same library can appear twice (root + entry "0"); keep the most informative.
    by_key: dict[str, dict] = {}
    for lib in libs:
        key = _key(lib["path"])
        prev = by_key.get(key)
        if prev is None or (prev["has_app"] is None and lib["has_app"] is not None):
            by_key[key] = lib
    return list(by_key.values())


def find_steam_install(tried: list | None = None) -> dict | None:
    if tried is None:
        tried = []
    for steam_root in steam_root_candidates():
        if not is_dir(steam_root):
            continue
        libs = steam_libraries(steam_root)
        ordered = [l for l in libs if l["has_app"] is True] + [l for l in libs if l["has_app"] is not True]
        for lib in ordered:
            steamapps = lib["path"] / "steamapps"
            installdir = "RimWorld"
            try:
                acf = parse_vdf(read_text(steamapps / f"appmanifest_{STEAM_APPID}.acf"))
                d = get_ci(get_ci(acf, "AppState"), "installdir")
                if isinstance(d, str) and d:
                    installdir = d
            except (OSError, ValueError):
                pass  # No manifest in this library - still try the default folder name.
            candidate = steamapps / "common" / installdir
            tried.append(candidate)
            if is_game_root(candidate):
                return {
                    "source": "steam",
                    "game_dir": candidate,
                    "steam_root": steam_root,
                    "workshop_dir": workshop_dir_for(candidate),
                }
    return None


def find_gog_install(tried: list | None = None) -> dict | None:
    if tried is None:
        tried = []
    candidates = []
    home = Path.home()
    if sys.platform == "win32":
        for key in ("HKLM\\SOFTWARE\\WOW6432Node\\GOG.com\\Games", "HKLM\\SOFTWARE\\GOG.com\\Games"):
            for b in read_reg_tree(key):
                v = b["values"]
                is_rimworld = (
                    "rimworld" in (v.get("gamename") or "").lower()
                    or "rimworld" in (v.get("exe") or "").lower()
                    or b["key"].lower().endswith(f"\\games\\{GOG_GAME_ID}")
                )
                if is_rimworld and v.get("path"):
                    candidates.append(norm(v["path"]))
        candidates += [Path("C:\\GOG Games\\RimWorld"), Path("C:\\Program Files (x86)\\GOG Galaxy\\Games\\RimWorld")]
    elif sys.platform == "linux":
        candidates += [home / "GOG Games" / "RimWorld" / "game", home / "GOG Games" / "RimWorld"]
    for c in dedupe(candidates):
        tried.append(c)
        game_dir = normalize_game_dir(c)
        if game_dir:
            return {"source": "gog", "game_dir": game_dir}
    return None


def default_config_dir() -> Path | None:
    """RimWorld's config folder (holds ModsConfig.xml). Same for Steam and GOG."""
    home = Path.home()
    sub = ("Ludeon Studios", "RimWorld by Ludeon Studios", "Config")
    if sys.platform == "win32":
        return home.joinpath("AppData", "LocalLow", *sub)
    if sys.platform == "linux":
        return home.joinpath(".config", "unity3d", *sub)
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "RimWorld" / "Config"
    return None


def autodetect() -> dict:
    """Runs every detector. `game` is the pick (Steam preferred), `games` all hits."""
    tried: list = []
    steam = find_steam_install(tried)
    gog = find_gog_install(tried)
    games = [g for g in (steam, gog) if g]
    cfg = default_config_dir()
    return {
        "game": games[0] if games else None,
        "games": games,
        "config_dir": cfg if cfg and is_dir(cfg) else None,
        "tried": tried,
    }


def workshop_dir_for(game_dir) -> Path:
    """Steam layout: <library>/steamapps/common/<installdir> ->
    <library>/steamapps/workshop/content/294100. Derived, never stored, so it
    can't go stale in settings.json."""
    return Path(os.path.normpath(os.path.join(game_dir, "..", "..", "workshop", "content", STEAM_APPID)))


def has_steam_appid(game_dir) -> bool:
    """Steam-integrated builds ship steam_appid.txt; GOG builds don't. Checked
    on disk, not via game_source, so a manually-Browsed Steam install counts."""
    return bool(game_dir and find_child_ci(game_dir, "steam_appid.txt"))


def mod_roots(game_dir) -> list[dict]:
    """Folders scanned for mods, in priority order (earlier wins on a duplicate
    packageId): Core/DLC in <game>/Data, local <game>/Mods, then Steam Workshop
    content when the install ships steam_appid.txt (missing folder skipped)."""
    game_dir = Path(game_dir)
    roots = [
        {"dir": game_dir / "Data", "source": "official"},
        {"dir": game_dir / "Mods", "source": "local"},
    ]
    if has_steam_appid(game_dir):
        ws = workshop_dir_for(game_dir)
        if is_dir(ws):
            roots.append({"dir": ws, "source": "workshop"})
    return roots


def read_game_version(game_dir) -> str | None:
    try:
        first = read_text(Path(game_dir) / "Version.txt").split("\n", 1)[0].strip()
    except (OSError, ValueError):
        return None
    return first or None
