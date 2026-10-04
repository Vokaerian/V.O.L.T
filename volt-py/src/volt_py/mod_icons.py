"""Mod icons for the Thunderstore managers' rows (0.6.26, PLAN.md §11 (b);
THUNDERSTORE.md §3d). Qt-free; the screen decodes the bytes.

A row's icon is the package's own icon.png - the 256x256 image Thunderstore
serves as the package's icon_url - read from what is already on disk, no
network: the per-game icon cache first, else the root icon.png of the
package's cached zip (every install goes through cache/packages/, local
.zip mods included), which is then copied into the icon cache so the next
run reads one small file. Third (0.6.40), when the caller passes the open
profile's folder and the package's load-order entry: the entry's own tracked
icon.png in that tree (own name or .disabled) - a profile copied / imported
from another VOLT brings its files but not that VOLT's caches - copied into
the icon cache the same way.

    <APP-ROOT>/cache/icons/<Team-Package-Version>.png

Keyed like the package cache (an update is a new key, so a changed icon
shows). No icon.png, an unreadable / missing zip -> b"" (the row keeps its
placeholder tile). Runs on the icon loader's worker threads.

Log (0.6.27): every call counts where its answer came from ("cache",
"copied" from a zip, "profile" from
the profile's own files, "none"); take_stats() hands the totals over and resets
them - the screen logs one line per batch of rows, never per paint.
"""

import os
import threading
import zipfile
from collections import Counter
from pathlib import Path

from . import thunderstore as ts
from .applog import log
from .bepinex_conflicts import _on_disk

ICONS_DIR = "icons"  # <APP-ROOT>/cache/icons/
ICON_FILE = "icon.png"  # a Thunderstore package's root icon (THUNDERSTORE.md §1)
MAX_BYTES = 2 << 20  # = thunderstore_browse.ICON_MAX_BYTES: anything bigger isn't an icon
_stats: Counter = Counter()
_stats_lock = threading.Lock()  # three loader workers count at once


def _count(kind: str) -> None:
    with _stats_lock:
        _stats[kind] += 1


def take_stats() -> dict[str, int]:
    """{"cache", "copied", "profile", "none"} counts since the last call (then reset)."""
    with _stats_lock:
        out = {k: _stats[k] for k in ("cache", "copied", "profile", "none")}
        _stats.clear()
    return out


def icon_key(entry: dict) -> str:
    """A load-order entry's cache key: "Team-Package-Version"."""
    return f"{entry['full_name']}-{entry['version']}"


def icon_cache_path(app_root, key: str) -> Path:
    return Path(app_root) / ts.CACHE_DIR / ICONS_DIR / f"{key}.png"


def load_icon(app_root, key: str, tree=None, entry: dict | None = None) -> bytes:
    """The icon.png bytes for `key` (module docstring), b"" when there is none.
    `tree` + `entry` (optional, 0.6.40): the open profile's folder and the
    package's load-order entry there (ignored unless its key is `key`)."""
    data = _load_icon(app_root, key, tree, entry)
    if not data:
        _count("none")
    return data


def _load_icon(app_root, key: str, tree, entry) -> bytes:
    cached = icon_cache_path(app_root, key)
    try:
        data = cached.read_bytes()
        _count("cache")
        return data
    except OSError:
        pass
    data, kind = _zip_icon(app_root, key), "copied"
    if not data and tree is not None and isinstance(entry, dict) \
            and f"{entry.get('full_name')}-{entry.get('version')}" == key:
        data, kind = _tree_icon(Path(tree), entry), "profile"
    if not data:
        return b""
    try:  # best effort: a failed write only means the source is read again next time
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_name(f"{cached.name}.{os.getpid()}.part")
        tmp.write_bytes(data)
        os.replace(tmp, cached)
    except OSError as err:
        log(f"[icons] {key}: cache write failed ({err})")
    _count(kind)
    return data


def _tree_icon(tree: Path, entry: dict) -> bytes:
    """The entry's tracked icon.png in the profile tree (the shallowest one:
    the package folder's own), b"" when none is there or it's over MAX_BYTES."""
    rels = [f for f in entry.get("files") or () if isinstance(f, str)
            and f.rsplit("/", 1)[-1].casefold() == ICON_FILE and ".." not in f.split("/")]
    for rel in sorted(rels, key=lambda f: f.count("/")):
        try:
            path = _on_disk(tree, rel)
            if path is not None and path.stat().st_size <= MAX_BYTES:
                return path.read_bytes()
        except (OSError, ValueError) as err:
            log(f"[icons] {entry.get('full_name')}: can't read {rel} ({err})")
    return b""


def _zip_icon(app_root, key: str) -> bytes:
    zip_path = ts.package_cache_dir(app_root) / f"{key}.zip"
    if not zip_path.is_file():
        return b""
    try:
        with zipfile.ZipFile(zip_path) as z:
            info = next((i for i in z.infolist() if i.filename.lower() == ICON_FILE), None)
            if info is None or info.file_size > MAX_BYTES:
                return b""
            data = z.read(info)
    except (OSError, zipfile.BadZipFile) as err:
        log(f"[icons] {key}: can't read {zip_path.name} ({err})")
        return b""
    return data
