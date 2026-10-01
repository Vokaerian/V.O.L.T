"""Mod scanning (port of Electron's src/electron/lib/mods.js): every
sub-folder of a mods root with About/About.xml is a mod. Mods are keyed by
lowercased packageId (RimWorld treats it case-insensitively and
ModsConfig.xml stores it lowercased).

Synchronous and sequential - result order matches the JS's Promise.all
(directory listing order) without the concurrency.
"""

import base64
import os
import re
from pathlib import Path

from .fsutil import find_child_ci, is_dds_only_leftover, is_dir, read_text
from .ids import NO_PACKAGE_ID_PREFIX
from .steamcmd_marker import read_marker_mode
from .xml import get_ci, list_, list_field, parse_xml, text

# An Offline copy's marker (offline_mods.MARKER). A Mods folder carrying it is a load order's Offline copy linked
# in for a Modded run (rimworld_launch.swap, 0.6.17) - or a stray one - never a live mod: the Mods scan skips it.
PINNED_MARKER = ".volt-pinned"


def _empty_about() -> dict:
    # A function, not a constant: make_mod keeps these lists by reference.
    return {
        "name": "", "package_id": "", "authors": [], "description": "",
        "supported_versions": [], "load_after": [], "load_before": [],
        "mod_dependencies": [], "incompatible_with": [],
    }


def parse_about_xml(xml_text: str) -> dict:
    """Raises ET.ParseError (a SyntaxError) on malformed XML, ValueError on
    a missing/empty <ModMetaData> root."""
    meta = parse_xml(xml_text)
    # len(meta) == 0: the JS parser turned a childless root into a string,
    # which failed its "is an object" check the same way.
    if meta.tag.lower() != "modmetadata" or len(meta) == 0:
        raise ValueError("no <ModMetaData> root element")
    authors = []
    single = text(get_ci(meta, "author"))
    if single:
        authors.append(single)
    for a in list_(get_ci(meta, "authors")):
        if a not in authors:
            authors.append(a)
    return {
        "name": text(get_ci(meta, "name")),
        "package_id": text(get_ci(meta, "packageId")),
        "authors": authors,
        "description": text(get_ci(meta, "description")),
        "supported_versions": list_(get_ci(meta, "supportedVersions")),
        # Raw packageIds as written (not lowercased); compare case-insensitively.
        "load_after": list_(get_ci(meta, "loadAfter")),
        "load_before": list_(get_ci(meta, "loadBefore")),
        # Hard dependencies: the packageId of each <li> (download info ignored).
        "mod_dependencies": list_field(get_ci(meta, "modDependencies"), "packageId"),
        # Plain <li>packageId</li> strings, like loadAfter.
        "incompatible_with": list_(get_ci(meta, "incompatibleWith")),
    }


def make_mod(about: dict, mod_dir, folder: str, source: str) -> dict:
    warnings = []
    mod_id = about["package_id"].lower()
    if not mod_id:
        mod_id = NO_PACKAGE_ID_PREFIX + folder.lower()
        warnings.append("About.xml has no packageId - this mod cannot be written to ModsConfig.xml.")
    return {
        "id": mod_id,
        **about,
        "name": about["name"] or folder,
        "path": mod_dir,
        "folder": folder,
        "source": source,
        "warnings": warnings,
    }


def scan_dir(dir, root_source: str) -> list[dict]:
    """One {"mod": ...} or {"problem": ...} per sub-folder of `dir`."""
    try:
        entries = list(os.scandir(dir))
    except FileNotFoundError:
        return [{"problem": {"kind": "missing-folder", "path": dir, "message": "Folder does not exist"}}]
    except OSError as e:
        raise OSError(f"Can't read mods folder {dir}: {e.strerror or e}") from e
    out = []
    for e in entries:
        if not (e.is_dir(follow_symlinks=False) or e.is_symlink()):
            continue
        mod_dir = Path(dir) / e.name
        if not is_dir(mod_dir):
            continue  # dangling link / symlink to a file
        # A Mods folder VOLT copied in from a SteamCMD download isn't a
        # hand-installed 'local' mod: its marker's mode decides. Only honoured
        # under Mods ('local' root).
        if root_source == "local" and os.path.isfile(mod_dir / PINNED_MARKER):
            continue  # an Offline copy linked in for a run (or a stray): the load order's, not a live mod
        source = (root_source == "local" and read_marker_mode(mod_dir)) or root_source
        out.append(scan_mod_dir(mod_dir, e.name, source))
    return out


def scan_mod_dir(mod_dir, folder: str, source: str) -> dict:
    """One mod folder: {"mod": ...} or {"problem": ...} (scan_dir's per-folder
    step; offline_mods.overlay parses an Offline copy with it too)."""
    about_dir = find_child_ci(mod_dir, "About")
    about_file = about_dir and find_child_ci(about_dir, "About.xml")
    if not about_file:
        # Narrow carve-out: a folder of nothing but .dds textures is listed
        # as a tagged no-packageId mod instead of a no-about scan issue.
        if is_dds_only_leftover(mod_dir, exclude_about_folder=False):
            return {"mod": {**make_mod(_empty_about(), mod_dir, folder, source), "dds_leftover": True}}
        return {"problem": {"kind": "no-about", "path": mod_dir, "message": "No About/About.xml - not a mod folder"}}
    try:
        about = parse_about_xml(read_text(about_file))
    except (OSError, ValueError, SyntaxError) as err:
        return {"problem": {"kind": "parse-error", "path": mod_dir, "message": f"About.xml could not be parsed: {err}"}}
    mod = make_mod(about, mod_dir, folder, source)
    # Only the no-packageId case is checked; About/ is skipped since
    # About.xml itself is never a .dds.
    if not about["package_id"] and is_dds_only_leftover(mod_dir, exclude_about_folder=True):
        mod["dds_leftover"] = True
    return {"mod": mod}


def sort_key_name(name) -> str:
    """Leading "[TAG]" groups (plus following whitespace) stripped, so
    "[NL] Custom Portraits" sorts under C. Falls back to the original name if
    nothing is left. Sort key only - the displayed name never changes."""
    s = "" if name is None else str(name)
    return re.sub(r"^(?:\[[^\]]*\]\s*)+", "", s) or s


def natural_key(s: str) -> list:
    # ponytail: casefold + numeric runs stands in for JS's
    # Intl.Collator({sensitivity:'base', numeric:true}). Doesn't do accent-
    # insensitivity (é != e) or locale-specific alphabet ordering the way ICU
    # would; swap in a real collation library if that's ever reported wrong.
    # re.split with a capture group keeps str at even / int at odd indexes, so
    # keys never compare int against str.
    return [int(t) if i % 2 else t.casefold() for i, t in enumerate(re.split(r"(\d+)", s))]


def workshop_id(mod: dict | None) -> str | None:
    """lists.js workshopId: a Workshop/SteamCMD/GOG-download mod's folder is
    its numeric Workshop id; None for anything else (or no mod). An Offline
    copy (source 'pinned', offline_mods.overlay) of such a mod keeps its
    folder name, so it counts by the origin it was copied from."""
    source = mod and mod["source"]
    if source == "pinned":
        source = (mod.get("pinned") or {}).get("origin")
    if source in ("workshop", "steamcmd", "gog") and re.fullmatch(r"\d+", mod["folder"], re.ASCII):
        return mod["folder"]
    return None



# Where a list row's mod comes from (RimWorld, 0.6.8 / RIMWORLD.md #52, user decision 2026-09-30): the mod
# right-click menu's header (<= 14 chars, so the menu never widens) and the details pane's Source row. One table,
# so the two can't disagree; keyed by the scan's source (scan_dir: the root, or a Mods folder's SteamCMD marker mode).
ORIGINS = {
    "workshop": ("Steam Workshop", "Steam Workshop (Steam's own folder)"),
    "steamcmd": ("SteamCMD copy", "SteamCMD download in your Mods folder (not synced to Steam yet)"),
    "gog": ("GOG copy", "SteamCMD download kept in your Mods folder (GOG)"),
    "local": ("Local mod", "Local mod (installed by hand in your Mods folder)"),
    "official": ("Official", "Official (Core / DLC)"),
    "pending": ("Pending", "Pending Steam Workshop item (not installed yet)"),
    "missing": ("Not installed", "Not installed"),
}
# An Offline copy's origin (offline_mods: the manifest entry's "origin"), worded for the details pane / row tooltip.
PINNED_FROM = {
    "mods": "your Mods folder",
    "steamcmd": "a SteamCMD copy in your Mods folder",
    "gog": "a GOG copy in your Mods folder",
    "workshop": "Steam's Workshop folder",
}


def origin(mod: dict | None, pending: bool = False) -> tuple[str, str]:
    """(menu header, details-pane text) for a row: its scanned mod's source,
    or for a not-found row (mod None) 'Pending' when it's a pending Workshop
    id (mod_list_io.not_found_workshop_id - the caller's answer), else
    'Not installed'."""
    if mod is None:
        return ORIGINS["pending" if pending else "missing"]
    if mod["source"] == "pinned":  # an Offline copy (offline_mods.overlay): where it was copied from
        src = PINNED_FROM.get((mod.get("pinned") or {}).get("origin"), "the live mod")
        text = f"Offline copy (this load order's own frozen copy, from {src}; not updated by Steam)"
        if mod.get("live_changed"):  # the screen's live-changed check (0.6.18; offline_mods.LIVE_CHANGED_NOTE)
            text += ". Live copy has changed since this Offline copy was made"
        return "Offline copy", text
    return ORIGINS.get(mod["source"], ORIGINS["local"])

def workshop_urls(mod: dict | None) -> dict | None:
    """lists.js workshopUrls: {"web", "steam"} links to the mod's Workshop page, or None."""
    wid = workshop_id(mod)
    if not wid:
        return None
    return {
        "web": f"https://steamcommunity.com/sharedfiles/filedetails/?id={wid}",
        "steam": f"steam://url/CommunityFilePage/{wid}",
    }


def dup_side(mod: dict) -> dict:
    """One side of a duplicate-id problem, for the Scan Issues window."""
    return {"name": mod["name"], "path": mod["path"], "workshop_id": workshop_id(mod)}


def scan_mod_roots(roots: list[dict]) -> dict:
    """roots: [{"dir", "source"}] (paths.mod_roots()). Earlier roots win on a
    duplicate package id."""
    mods = []
    problems = []
    by_id = {}
    for root in roots:
        for r in scan_dir(root["dir"], root["source"]):
            if "problem" in r:
                problems.append(r["problem"])
                continue
            m = r["mod"]
            prev = by_id.get(m["id"])
            if prev:
                prev["warnings"].append(f"Another copy with the same package ID is at {m['path']} (ignored).")
                problems.append({
                    "kind": "duplicate-id",
                    "path": m["path"],
                    "message": f"Duplicate package ID \"{m['package_id']}\"\n\nKept: {prev['name']}\n{prev['path']}\n\nIgnored: {m['name']}\n{m['path']}",
                    "kept": dup_side(prev),
                    "ignored": dup_side(m),
                })
                continue
            by_id[m["id"]] = m
            mods.append(m)
    mods.sort(key=lambda m: natural_key(sort_key_name(m["name"])))
    return {"mods": mods, "problems": problems}


def read_preview_data_url(mod_dir) -> str | None:
    """<mod_dir>/About/Preview.png (case-insensitive) as a data URL, or None."""
    about_dir = find_child_ci(mod_dir, "About")
    file = about_dir and find_child_ci(about_dir, "Preview.png")
    if not file:
        return None
    try:
        return "data:image/png;base64," + base64.b64encode(file.read_bytes()).decode("ascii")
    except OSError:
        return None
