"""Offline mods (RimWorld; RIMWORLD.md PLAN item 10, stage 2, 0.6.16): a load
order's own frozen copy of a mod, kept in <LO>/local-mods/<folder>/ and
recorded in the manifest's `pinning` block (load_orders.set_pinning), keyed by
lowercased packageId like the rest of the app:

  pinning.mods[<packageId>] = {"folder", "origin": "mods" | "steamcmd" | "gog"
      | "workshop", "workshop_id"?, "copied_at", "size_bytes", "source_path"}

The copy keeps the source folder's name (RimWorld keys per-mod settings files
on it: Mod_<folder>_<Class>.xml) and carries a MARKER file (JSON: origin,
copied_at, package_id); a SteamCMD copy's own .volt-steamcmd marker is left
out, so nothing treats the copy as a SteamCMD download. Copies land in a
`.tmp-<folder>` sibling first and are renamed into place only when complete:
a failed or cancelled copy leaves nothing behind (the manifest is the
caller's to update, after success). Making a mod live again deletes its copy,
path-contained to the load order's own local-mods folder (never through a
link).

overlay() is the per-load-order view of the global scan: each entry's copy,
parsed with mods.scan_mod_dir as source 'pinned', replaces (or supplies) the
mod with that packageId - in a new dict, the scan's own dict and mod dicts
untouched. At Modded Run (own game data on) rimworld_launch.swap links the
active ones as Mods/<folder> -> <LO>/local-mods/<folder> and removes the
links when the game closes (OFFLINE_RUN_TEXT, 0.6.17).

Plain stdlib, no Qt (tools/checks/volt_py_offline_mods.py).
"""

import hashlib
import json
import math
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .fsutil import is_dir, is_link, remove_tree_best_effort, write_text_atomic
from .ids import NO_PACKAGE_ID_PREFIX, PENDING_WORKSHOP_PREFIX
from .mods import PINNED_MARKER, scan_mod_dir, workshop_id
from .steamcmd_marker import LEGACY_MARKER
from .steamcmd_marker import MARKER as STEAMCMD_MARKER

LOCAL_MODS_DIR = "local-mods"
MARKER = PINNED_MARKER  # ".volt-pinned"; the Mods scan skips a folder carrying it (mods.scan_dir)
TMP_PREFIX = ".tmp-"  # an unfinished copy (renamed into place when complete)
DEL_PREFIX = ".del-"  # a copy moved aside to be deleted (Make live again)
OLD_PREFIX = ".old-"  # the previous copy during a Refresh, until the new one is in place (0.6.18)
# What a Run does with them (0.6.17): the dialog footer, the Make Offline confirm, Help.
OFFLINE_RUN_TEXT = (
    "When you press Modded, the active Offline mods are linked into the game's Mods folder and removed again when the "
    "game closes (load orders with Own game data on)."
)
# The row tooltip's note (mod_decorations.row_tooltip) and a missing copy's "!" warning.
OFFLINE_NOTE = "Offline copy: this load order's own frozen copy, not updated by Steam"
MISSING_WARNING = "This load order's Offline copy is missing or unreadable - the live mod is shown instead."
# Live-changed detection (0.6.18): live_status() values, their dialog-column labels, the row tooltip /
# details line when the live mod changed since the copy was made.
LIVE_LABEL = {"same": "Same", "changed": "Changed", "not-installed": "Not installed", "unknown": "?"}
LIVE_CHANGED_NOTE = "Live copy has changed since this Offline copy was made"
# The scan's source (mods.scan_dir) -> the entry's origin. Anything else (official, pinned) can't be copied.
ORIGIN_OF_SOURCE = {"local": "mods", "steamcmd": "steamcmd", "gog": "gog", "workshop": "workshop"}
# Top-level files never copied: another manager's markers (and an old copy's own).
_STRIP = frozenset((STEAMCMD_MARKER, LEGACY_MARKER, MARKER))
_BAD_FOLDER = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class OfflineError(Exception):
    """A plain-message refusal / failure (shown to the user as is)."""


class Cancelled(OfflineError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def valid_folder(name) -> bool:
    """A folder name an entry may carry: one plain path component (no
    separators, no '.'/'..', no leading dot - those are this module's own
    temp names), so a manifest can never point outside local-mods."""
    return (isinstance(name, str) and bool(name) and name == name.strip() and not name.startswith(".")
            and not _BAD_FOLDER.search(name) and os.path.basename(name) == name)


def normalize_pinning(raw, default: dict) -> dict:
    """The manifest's pinning block: unknown fields kept, `dir` always
    LOCAL_MODS_DIR (pre-0.6.16 manifests said "pinned"; nothing used it),
    `mods` keyed by lowercased packageId with only well-formed entries (a dict
    with a valid_folder), `enabled` = any entry."""
    p = {**default, **(raw if isinstance(raw, dict) else {})}
    entries = p.get("mods") if isinstance(p.get("mods"), dict) else {}
    mods = {}
    for key, e in entries.items():
        pid = key.strip().lower() if isinstance(key, str) else ""
        if pid and isinstance(e, dict) and valid_folder(e.get("folder")):
            mods[pid] = e
    return {**p, "dir": LOCAL_MODS_DIR, "mods": mods, "enabled": bool(mods)}


def local_mods_dir(lo_dir) -> Path:
    return Path(lo_dir) / LOCAL_MODS_DIR


def copy_path(lo_dir, folder) -> Path:
    """<lo_dir>/local-mods/<folder>, refused (OfflineError) unless it is
    directly inside that load order's own local-mods folder: a valid_folder
    name, local-mods itself not a link, the parent resolving to it."""
    if not valid_folder(folder):
        raise OfflineError(f"{folder!r} isn't a usable Offline folder name.")
    local = local_mods_dir(lo_dir)
    if is_link(local):
        raise OfflineError(f"{local} is a link, not a folder - VOLT won't write or delete through it.")
    target = local / folder
    if (os.path.dirname(os.path.abspath(target)) != os.path.abspath(local)
            or (local.exists() and target.parent.resolve() != local.resolve())):
        raise OfflineError(f"{target} isn't inside this load order's local-mods folder.")
    return target


def refusal(mod_id: str, mod: dict | None, entries: dict) -> str | None:
    """Why `mod_id` (its scanned / overlaid mod, None for a not-found row)
    can't be made Offline in a load order with these `entries` (the pinning
    mods, plus anything else already claiming a folder name); None = it can."""
    name = mod["name"] if mod else mod_id
    if mod_id in entries or (mod is not None and mod["source"] == "pinned"):
        return f"{name} is already Offline in this load order."
    if mod_id.startswith(PENDING_WORKSHOP_PREFIX) or (mod is None and re.fullmatch(r"\d+", mod_id, re.ASCII)):
        return f"{name} is a pending Steam Workshop item: it isn't installed, so there's nothing to copy."
    if mod_id.startswith(NO_PACKAGE_ID_PREFIX):
        return f"{name} has no packageId in its About.xml, so VOLT can't keep an Offline copy of it."
    if mod is None:
        return f"{name} isn't installed, so there's nothing to copy."
    if mod["source"] == "official" or mod_id.startswith("ludeon."):
        return f"{name} is part of RimWorld itself (Core or a DLC), so it can't be made Offline."
    if mod["source"] not in ORIGIN_OF_SOURCE:
        return f"{name} comes from a place VOLT can't copy from ({mod['source']})."
    path = mod["path"]
    if not is_dir(path) or not os.access(path, os.R_OK):
        return f"{name}'s folder can't be read ({path})."
    folder = mod["folder"]
    if not valid_folder(folder):
        return f'{name}\'s folder name "{folder}" can\'t be used for an Offline copy.'
    clash = next((pid for pid, e in entries.items() if str(e.get("folder", "")).casefold() == folder.casefold()), None)
    if clash is not None:
        return f'Another Offline mod in this load order ({clash}) already uses the folder name "{folder}".'
    return None


def size_of(path, cancel=None) -> int:
    """Bytes in the files under `path` (links not followed; unreadable
    entries skipped; a missing path is 0). `cancel` (a threading.Event) set:
    raises Cancelled. For a worker thread."""
    total = 0
    stack = [os.fspath(path)]
    while stack:
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False) and not is_link(e.path):
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    total += e.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    return total


def format_size(n: int | None) -> str:
    if n is None:
        return "..."
    for unit, f in (("GB", 1024**3), ("MB", 1024**2)):
        if n >= f:
            return f"{n / f:.1f} {unit}"
    return f"{math.ceil(n / 1024)} KB"


def fingerprint(path, cancel=None) -> str | None:
    """A cheap fingerprint of a mod folder's files: sha1 over the sorted
    (relative path, size, mtime_ns) of every file (no contents read; links
    not followed; the top-level markers left out - they differ between a
    source and its copy). None when `path` isn't a readable folder.
    `cancel` set: Cancelled. For a worker thread."""
    root = os.fspath(path)
    if not os.path.isdir(root):
        return None
    rows = []
    stack = [root]
    while stack:
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False) and not is_link(e.path):
                    stack.append(e.path)
                elif e.is_file(follow_symlinks=False):
                    if d == root and e.name in _STRIP:
                        continue
                    st = e.stat(follow_symlinks=False)
                    rel = os.path.relpath(e.path, root).replace(os.sep, "/")
                    rows.append(f"{rel}\t{st.st_size}\t{st.st_mtime_ns}")
            except OSError:
                pass
    h = hashlib.sha1()
    for row in sorted(rows):
        h.update(row.encode("utf-8", "surrogatepass") + b"\n")
    return h.hexdigest()


def live_status(entry: dict, live_mod: dict | None, current: str | None) -> str:
    """An Offline entry against its live mod (the global scan's, never the
    overlay): "not-installed" (no live mod), "unknown" (no stored
    fingerprint - copied before 0.6.18 - or the live one couldn't be read),
    "same" / "changed"."""
    if live_mod is None:
        return "not-installed"
    stored = entry.get("fingerprint")
    if not stored or not current:
        return "unknown"
    return "same" if stored == current else "changed"


def _remove(path) -> list[dict]:
    """Deletes `path` (a link: just the link); returns what couldn't be removed."""
    if not os.path.lexists(path):
        return []
    if is_link(path):
        try:
            os.unlink(path)
        except (IsADirectoryError, PermissionError):
            os.rmdir(path)  # Windows removes a directory link / junction as a directory
        return []
    return remove_tree_best_effort(path)["skipped"]


def _copy_in(src, lo_dir, folder: str, marker: dict, cancel=None, on_bytes=None, replace_leftover: bool = False) -> int:
    """Copies the folder `src` to <lo_dir>/local-mods/<folder> through a temp
    sibling + rename, MARKER written, the _STRIP markers left out. Returns
    the bytes copied. Any failure / Cancelled leaves nothing behind. An
    existing destination is refused - unless `replace_leftover` (the caller
    read the manifest cleanly and no entry uses this folder) and it is one of
    VOLT's own unrecorded copies (a MARKER inside, not a link): then it is
    deleted (make_live) and copied afresh. A .tmp- leftover is always replaced."""
    dest = copy_path(lo_dir, folder)
    if (replace_leftover and os.path.lexists(dest) and not is_link(dest)
            and os.path.isfile(os.path.join(dest, MARKER))):
        make_live(lo_dir, folder)  # an unrecorded copy of ours (e.g. a crash before the manifest write)
    if os.path.lexists(dest):
        raise OfflineError(f'A folder "{folder}" is already in this load order\'s local-mods folder ({dest}) but isn\'t '
                           "recorded as Offline - delete it there, then try again.")
    tmp = dest.with_name(TMP_PREFIX + folder)
    _remove(tmp)  # an interrupted earlier copy
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = _copy_tree(src, tmp, marker, cancel, on_bytes)
    try:
        os.rename(tmp, dest)
    except BaseException:
        _remove(tmp)
        raise
    return total


def _copy_tree(src, tmp, marker: dict, cancel=None, on_bytes=None) -> int:
    """copytree `src` -> `tmp` (the _STRIP markers left out, MARKER written,
    cancel / progress per file); returns the bytes copied. Any failure
    removes `tmp` (a shutil.Error becomes one plain OfflineError)."""
    top = os.fspath(src)
    total = 0

    def copy(s, d):
        nonlocal total
        # ponytail: cancel / progress per file - one huge file copies uninterrupted; chunked copying if that matters
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")
        shutil.copy2(s, d)
        n = os.path.getsize(d)
        total += n
        if on_bytes is not None:
            on_bytes(n)

    try:
        shutil.copytree(src, tmp, copy_function=copy,
                        ignore=lambda d, names: [n for n in names if n in _STRIP] if d == top else [])
        write_text_atomic(Path(tmp) / MARKER, json.dumps(marker, separators=(",", ":")) + "\n")
        if cancel is not None and cancel.is_set():
            raise Cancelled("Cancelled.")
    except BaseException as err:
        _remove(tmp)
        if isinstance(err, shutil.Error):  # copytree's per-file failures, collected
            first = err.args[0][0] if err.args and err.args[0] else None
            raise OfflineError(f"{len(err.args[0])} file(s) couldn't be copied"
                               + (f" (first: {first[0]}: {first[2]})" if first else "") + ".") from err
        raise
    return total


def make_offline(lo_dir, mod: dict, cancel=None, on_bytes=None, entries: dict | None = None) -> dict:
    """Copies the scanned `mod` (from mod["path"], whichever copy the scan
    chose) into the load order; returns its new manifest entry. The caller
    has checked refusal() and records the entry only after this returns.
    `entries`: the load order's entries from a cleanly read manifest (None =
    unread / unreadable); only with them may a leftover copy of ours in the
    destination folder, referenced by no entry, be replaced (_copy_in)."""
    origin = ORIGIN_OF_SOURCE.get(mod["source"])
    if origin is None:
        raise OfflineError(f"{mod['name']} can't be made Offline (source {mod['source']}).")
    copied_at = _now()
    wid = workshop_id(mod)
    folder = mod["folder"]
    fp = fingerprint(mod["path"], cancel)  # the source as copied (0.6.18: live-changed detection)
    unreferenced = entries is not None and not any(
        str(e.get("folder", "")).casefold() == folder.casefold() for e in entries.values())
    size = _copy_in(mod["path"], lo_dir, folder,
                    {"origin": origin, "copied_at": copied_at, "package_id": mod["package_id"]}, cancel, on_bytes,
                    replace_leftover=unreferenced)
    return {"folder": mod["folder"], "origin": origin, **({"workshop_id": wid} if wid else {}),
            "copied_at": copied_at, "size_bytes": size, "source_path": str(mod["path"]),
            **({"fingerprint": fp} if fp else {})}


def refresh(lo_dir, live_mod: dict, entry: dict, cancel=None, on_bytes=None) -> dict:
    """Refresh Offline copy: the live mod (the global scan's) copied afresh
    into the entry's folder (its name kept). The new copy goes to .tmp-
    first; only then is the old one renamed aside (.old-) and the new one
    renamed into place - a failure anywhere before leaves the old copy as it
    was, a failed final rename puts the old one back. Returns the updated
    entry (origin / workshop_id / copied_at / size / source / fingerprint).
    A MISSING copy (its folder gone - hardware review 2026-10-01) is simply
    recreated from the live mod: the same .tmp- copy, moved into place."""
    folder = entry["folder"]
    dest = copy_path(lo_dir, folder)
    if is_link(dest) or (os.path.lexists(dest) and not is_dir(dest)):
        raise OfflineError(f"{dest} isn't a folder VOLT can refresh - make the mod live again, then Offline.")
    origin = ORIGIN_OF_SOURCE.get(live_mod["source"])
    if origin is None:
        raise OfflineError(f"{live_mod['name']} can't be copied from (source {live_mod['source']}).")
    copied_at = _now()
    fp = fingerprint(live_mod["path"], cancel)
    tmp = dest.with_name(TMP_PREFIX + folder)
    _remove(tmp)
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = _copy_tree(live_mod["path"], tmp,
                      {"origin": origin, "copied_at": copied_at, "package_id": live_mod["package_id"]}, cancel, on_bytes)
    if not os.path.lexists(dest):  # the copy was missing: the new one just moves in
        try:
            os.rename(tmp, dest)
        except BaseException:
            _remove(tmp)
            raise
        return _refreshed(entry, live_mod, origin, copied_at, size, fp)
    old = dest.with_name(f"{OLD_PREFIX}{folder}-{time.time_ns()}")
    try:
        os.rename(dest, old)
    except OSError as err:
        _remove(tmp)
        raise OfflineError(f"Couldn't replace the Offline copy in {dest} ({err.strerror or err}). "
                           "Is one of its files open? The old copy is unchanged.") from err
    try:
        os.rename(tmp, dest)
    except OSError:
        os.rename(old, dest)  # the old copy back in place
        _remove(tmp)
        raise
    _remove(old)  # best effort; a leftover .old- is swept later
    return _refreshed(entry, live_mod, origin, copied_at, size, fp)


def _refreshed(entry: dict, live_mod: dict, origin: str, copied_at: str, size: int, fp) -> dict:
    wid = workshop_id(live_mod)
    new = {k: v for k, v in entry.items() if k != "workshop_id"}
    return {**new, "origin": origin, **({"workshop_id": wid} if wid else {}), "copied_at": copied_at,
            "size_bytes": size, "source_path": str(live_mod["path"]), **({"fingerprint": fp} if fp else {})}


def copy_entry(src_lo_dir, dst_lo_dir, pid: str, entry: dict, cancel=None, on_bytes=None) -> dict:
    """Copy to new load order: the source load order's copy of `pid` becomes
    an independent copy in `dst_lo_dir`; returns the new entry (same origin
    and copied_at - the content is the same frozen copy)."""
    src = copy_path(src_lo_dir, entry["folder"])
    if not is_dir(src):
        raise OfflineError(f"its Offline copy is missing ({src}).")
    size = _copy_in(src, dst_lo_dir, entry["folder"],
                    {"origin": entry.get("origin"), "copied_at": entry.get("copied_at"), "package_id": pid},
                    cancel, on_bytes)
    return {**entry, "size_bytes": size}


def make_live(lo_dir, folder: str) -> list[dict]:
    """Make live again: deletes <lo_dir>/local-mods/<folder> (copy_path's
    containment; a link there is unlinked, never followed). The folder is
    first renamed aside (refused with OfflineError, nothing changed, if
    Windows holds a file in it), then deleted best-effort: returns what
    couldn't be removed (harmless dot-folder leftovers, swept later). A
    missing copy is fine. The caller drops the manifest entry afterwards."""
    target = copy_path(lo_dir, folder)
    if not os.path.lexists(target):
        return []
    if is_link(target):
        return _remove(target)
    trash = target.with_name(f"{DEL_PREFIX}{folder}-{time.time_ns()}")
    try:
        os.rename(target, trash)
    except OSError as err:
        raise OfflineError(f"Couldn't remove the Offline copy in {target} ({err.strerror or err}). "
                           "Is one of its files open?") from err
    return _remove(trash)


def sweep(lo_dir) -> None:
    """Best-effort removal of temp / aside folders an interrupted run left in
    the load order's local-mods folder. A Refresh's .old-<folder>-<n> whose
    <folder> is missing (interrupted between the two renames) is renamed
    back instead - the copy is never lost."""
    local = local_mods_dir(lo_dir)
    try:
        names = [n for n in os.listdir(local) if n.startswith((TMP_PREFIX, DEL_PREFIX, OLD_PREFIX))]
    except OSError:
        return
    for n in sorted(names, key=lambda n: not n.startswith(OLD_PREFIX)):  # .old- first, then the rest
        if n.startswith(OLD_PREFIX):
            folder = n[len(OLD_PREFIX):].rsplit("-", 1)[0]
            if valid_folder(folder) and not os.path.lexists(local / folder) and not is_link(local / n):
                try:
                    os.rename(local / n, local / folder)
                    continue
                except OSError:
                    pass
            elif not os.path.lexists(local / folder):
                continue  # can't restore, never delete the only copy
        _remove(local / n)


def overlay(live: dict, entries: dict, lo_dir) -> tuple[dict, list[dict]]:
    """The load order's view of the scan: (mods, problems). Each entry's copy
    (scanned as source 'pinned', the entry under "pinned") replaces the live
    mod with that packageId, or supplies it when it isn't installed. A copy
    that is missing, unreadable or now has another packageId keeps the live
    mod (a copy of it with MISSING_WARNING added, so its row gets the "!")
    or the not-found row, plus an 'offline-missing' problem. `live` and its
    mods are never mutated; with no entries `live` itself is returned."""
    if not entries:
        return live, []
    out, problems = dict(live), []
    for pid, e in entries.items():
        try:
            path = copy_path(lo_dir, e.get("folder"))
            r = scan_mod_dir(path, e["folder"], "pinned") if is_dir(path) else {"problem": {"message": "the folder is missing"}}
        except OfflineError as err:
            path, r = local_mods_dir(lo_dir), {"problem": {"message": str(err)}}
        mod = r.get("mod")
        if mod is not None and mod["id"] == pid:
            out[pid] = {**mod, "pinned": dict(e)}
            continue
        why = (r["problem"]["message"] if mod is None
               else f"its About.xml now says packageId \"{mod['package_id'] or '(none)'}\"")
        name = live[pid]["name"] if pid in live else pid
        problems.append({"kind": "offline-missing", "path": path, "message": f"Offline copy of {name} missing or unreadable: {why}"})
        if pid in out:
            out[pid] = {**out[pid], "warnings": [*out[pid]["warnings"], MISSING_WARNING]}
    return out, problems
