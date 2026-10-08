"""The bulk community package index (0.6.51, THUNDERSTORE.md TODO #19): one
download of a game's whole Thunderstore community, so the exact-version
dependency walk (install_mod, the plan_downloads pre-pass, the browser's
Required chain - thunderstore_browse.dependency_chain) needs no per-package
request for a package version the index has. What Gale and r2modman use:

  GET /c/<community>/api/v1/package-listing-index/ -> a gzipped JSON list of
  chunk URLs; each chunk -> a gzipped JSON list of v1 package listings
  ({full_name, ..., versions: [{version_number, dependencies, ...}]}).

Measured 2026-10-08 on the user's machine (Lethal Company): 25 chunks, 34.7
MB downloaded, 347.9 MB unpacked, 51,115 packages / 194,664 versions. Kept
whole as Python objects that is 542 MB, so it never is: build() downloads the
chunks FETCH_WORKERS at a time but parses them one at a time, in order, and
writes each package straight into a zip on disk - one member per package
(name = full_name, data = {"versions": {version: [dependency strings]},
"date_updated", "deprecated"} as JSON, deflated - the last two since 0.6.52,
for the update check); nothing but the package names is kept across chunks. The zip's
comment holds {"format", "community", "built_at", "packages"}. A
PackageIndex reads one member per lookup (the zip's CRC checks it), so the
loaded index is the file's bytes plus its directory (~60 MB for LC), not a
dict of every version.

<APP-ROOT>/cache/package-index.zip, one per game (APP-ROOT is per game).
Fresh for TTL_S (24 h; Gale re-fetches every 15 min, but a stale index only
ever costs requests: a version or package it lacks is looked up per package,
as before) for the dependency lookups; the update check
(bepinex_load_orders.check_updates, 0.6.52) asks for one at most
UPDATE_MAX_AGE_S (1 h) old - the same file, rebuilt when it is older (the
max_age_s of current() / ensure()). A failed build isn't retried for
RETRY_AFTER_S in this run, so an offline pre-pass doesn't wait on it every
time. Never required: no index, a
stale one, a failed build, a corrupt or oversized file (discarded, never
trusted) - the callers fall back to the per-package endpoints exactly as
0.6.50 did. current() never touches the network (install_mod); ensure()
builds when needed (the pre-pass and the browser's chain, both off the GUI
thread). An unversioned ref (Add mod by name, Install missing) never uses
the index: "latest" is asked of Thunderstore, the index may be a day old.

Stdlib only (urllib through thunderstore_browse._get / thunderstore.env, the
harness seam; gzip/zlib/json/zipfile). tools/checks/volt_py_package_index.py
fakes the chunks.
"""

import io
import json
import os
import threading
import time
import types
import zipfile
import zlib
from pathlib import Path

from . import thunderstore as ts
from . import thunderstore_browse as tb
from .applog import clip, log
from .thunderstore import ThunderstoreError

INDEX_FILE = "package-index.zip"  # <APP-ROOT>/cache/package-index.zip
FORMAT = 2  # 0.6.52: members carry date_updated / deprecated (a format-1 file is discarded and rebuilt)
TTL_S = 24 * 3600  # dependency lookups
UPDATE_MAX_AGE_S = 3600  # the update check (0.6.52): Thunderstore's latest at most an hour behind
RETRY_AFTER_S = 600.0
LIST_MAX_BYTES = 1 << 20  # the chunk-URL list (real: 1,307 B)
CHUNK_MAX_BYTES = 64 << 20  # one gzipped chunk (real: ~1.4 MB)
UNPACKED_MAX_BYTES = 256 << 20  # one chunk unpacked (real: ~14 MB) - a bigger one is refused, not inflated
FILE_MAX_BYTES = 256 << 20  # the cache file (real: ~32 MB); bigger = discarded
CHUNK_TIMEOUT_S = 60.0  # per socket operation

# Check-harness seam: the clock that dates an index (TTL) and paces retries.
env = types.SimpleNamespace(clock=time.time)


def index_url(community: str) -> str:
    return f"{ts.SITE}/c/{community}/api/v1/package-listing-index/"


def index_path(app_root) -> Path:
    return Path(app_root) / ts.CACHE_DIR / INDEX_FILE


class PackageIndex:
    """A loaded index file: `community`, `built_at` (env.clock() time),
    `packages` (count); `full_name in index`; lookup(ref). A member that
    fails its CRC / doesn't parse marks the index `broken` (current() then
    discards the file) and reads as a miss."""

    def __init__(self, data: bytes, path):
        self.path = Path(path)
        self._zip = zipfile.ZipFile(io.BytesIO(data))
        meta = json.loads(self._zip.comment.decode("utf-8"))
        if not (isinstance(meta, dict) and meta.get("format") == FORMAT and isinstance(meta.get("community"), str)
                and isinstance(meta.get("built_at"), (int, float))):
            raise ValueError(f"not a VOLT package index (comment {clip(meta, 200)})")
        self.community, self.built_at, self.packages = meta["community"], float(meta["built_at"]), meta.get("packages")
        self.broken = False
        self._lock = threading.Lock()  # one member read at a time (the chain's lookups run on worker threads)

    def __contains__(self, full_name) -> bool:
        try:
            self._zip.getinfo(full_name)
        except KeyError:
            return False
        return True

    def fresh(self, max_age_s: float = TTL_S) -> bool:
        return not self.broken and 0 <= env.clock() - self.built_at < max_age_s

    def _member(self, full_name: str) -> dict | None:
        if full_name not in self:
            return None
        try:
            with self._lock:
                raw = self._zip.read(full_name)
            got = json.loads(raw)
        except (zipfile.BadZipFile, zlib.error, ValueError, OSError) as err:
            log(f"[index] {self.path}: {full_name} unreadable ({err!r}) - the index is discarded")
            self.broken = True
            return None
        return got if isinstance(got, dict) and isinstance(got.get("versions"), dict) else None

    def versions(self, full_name: str) -> dict | None:
        """{version: [dependency strings]} of a package, None when the index hasn't it."""
        return (self._member(full_name) or {}).get("versions")

    def latest(self, full_name: str) -> dict | None:
        """{"latest_version", "date_updated", "deprecated"} of a package (the
        update check, 0.6.52), None when the index hasn't it. Latest = the
        highest version by ts.version_key - is_newer's order, and
        Thunderstore's own (its versions list is sorted by version, highest
        first, which is what Gale reads as the latest)."""
        m = self._member(full_name) if not self.broken else None
        if not m or not m["versions"]:
            return None
        return {"latest_version": max(m["versions"], key=ts.version_key),
                "date_updated": m.get("date_updated") if isinstance(m.get("date_updated"), str) else None,
                "deprecated": m.get("deprecated") is True}

    def lookup(self, ref: ts.PackageRef) -> tuple[str, list[str]] | None:
        """(version, its dependency strings) for a pinned `ref` the index has;
        None for anything else (an unversioned ref included: module docstring)."""
        if ref.version is None or self.broken:
            return None
        deps = (self.versions(ref.full_name) or {}).get(ref.version)
        return (ref.version, [d for d in deps if isinstance(d, str)]) if isinstance(deps, list) else None


def _gunzip(body: bytes, what: str) -> bytes:
    """A gzip body unpacked (a plain one as is), at most UNPACKED_MAX_BYTES."""
    if body[:2] != b"\x1f\x8b":
        return body
    d = zlib.decompressobj(wbits=31)
    try:
        data = d.decompress(body, UNPACKED_MAX_BYTES)
    except zlib.error as err:
        raise ThunderstoreError(f"Thunderstore's {what} isn't readable gzip ({err}).") from err
    if d.unconsumed_tail:
        raise ThunderstoreError(f"Thunderstore's {what} unpacks to more than {UNPACKED_MAX_BYTES >> 20} MB.")
    return data


def _trim(p) -> tuple[str, dict] | None:
    """(full_name, its member: {"versions": {version: [dependency strings]},
    "date_updated", "deprecated"}) of one v1 listing; None for anything that
    isn't a package with a usable version."""
    if not isinstance(p, dict):
        return None
    try:
        ref = ts.PackageRef.parse(p.get("full_name"))
    except ValueError:
        return None
    if ref.version is not None:
        return None
    out = {}
    for v in p.get("versions") if isinstance(p.get("versions"), list) else ():
        number = v.get("version_number") if isinstance(v, dict) else None
        if isinstance(number, str) and ts.version_key(number) != (-1,):
            deps = v.get("dependencies")
            out[number] = [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
    if not out:
        return None
    date = p.get("date_updated")
    return ref.full_name, {"versions": out, "date_updated": date if isinstance(date, str) else None,
                           "deprecated": p.get("is_deprecated") is True}


def _chunks(urls: list[str], app_version, workers: int):
    """Yields each chunk's (gzipped) body in list order, while up to
    `workers` daemon threads download ahead (thunderstore_browse._parallel:
    closing VOLT mid-build never waits on them). A failed chunk raises here."""
    bodies: dict[int, object] = {}
    cond, stop, n = threading.Condition(), threading.Event(), len(urls)

    def one(i: int) -> None:
        if stop.is_set():
            return
        try:
            got = tb._get(urls[i], app_version, f"package list (part {i + 1} of {n})", max_bytes=CHUNK_MAX_BYTES,
                          timeout=CHUNK_TIMEOUT_S)
        except Exception as err:  # noqa: BLE001 - handed to the reader, which raises it
            got = err
        with cond:
            bodies[i] = got
            cond.notify_all()

    threading.Thread(target=tb._parallel, args=(range(n), one, workers), name="index-chunks", daemon=True).start()
    try:
        for i in range(n):
            with cond:
                cond.wait_for(lambda: i in bodies)  # every _get has its socket timeout, so this ends
                got = bodies.pop(i)
            if isinstance(got, Exception):
                raise got
            yield got
    finally:
        stop.set()


def build(app_root, community: str, app_version=None, *, workers: int = tb.FETCH_WORKERS, on_start=None) -> PackageIndex:
    """Downloads `community`'s whole package listing and writes the index
    file (temp sibling + os.replace); returns it loaded. `on_start()` runs
    once the chunk list is in (the download bar's "Updating package
    list..."). ThunderstoreError / OSError / ValueError on any failure -
    nothing is written then (an older file stays as it was)."""
    start = time.monotonic()
    body = tb._get(index_url(community), app_version, "package list index", max_bytes=LIST_MAX_BYTES)
    try:
        urls = json.loads(_gunzip(body, "package list index"))
    except ValueError as err:
        raise ThunderstoreError(f"Thunderstore's package list index isn't JSON ({err}).") from err
    if not (isinstance(urls, list) and urls and all(isinstance(u, str) and u.startswith("https://") for u in urls)):
        raise ThunderstoreError(f"Thunderstore's package list index has an unexpected shape: {clip(urls, 300)}")
    log(f"[index] {community}: {len(urls)} chunks to fetch, {workers} at a time")
    if on_start is not None:
        on_start()
    path = index_path(app_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.part")
    names: set[str] = set()
    got_bytes = unpacked = versions = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, chunk in enumerate(_chunks(urls, app_version, workers)):
                got_bytes += len(chunk)
                data = _gunzip(chunk, f"package list (part {i + 1})")
                unpacked += len(data)
                try:
                    listing = json.loads(data)
                except ValueError as err:
                    raise ThunderstoreError(f"Thunderstore's package list (part {i + 1}) isn't JSON ({err}).") from err
                del data, chunk
                if not isinstance(listing, list):
                    raise ThunderstoreError(f"Thunderstore's package list (part {i + 1}) has an unexpected shape.")
                for p in listing:
                    trimmed = _trim(p)
                    if trimmed is None or trimmed[0] in names:
                        continue
                    names.add(trimmed[0])
                    versions += len(trimmed[1]["versions"])
                    zf.writestr(trimmed[0], json.dumps(trimmed[1], separators=(",", ":")))
                del listing
            if not names:
                raise ThunderstoreError("Thunderstore's package list is empty.")
            zf.comment = json.dumps({"format": FORMAT, "community": community, "built_at": env.clock(),
                                     "packages": len(names)}).encode("utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    index = PackageIndex(path.read_bytes(), path)
    log(f"[index] {community}: built in {time.monotonic() - start:.1f}s - {len(urls)} chunks, {got_bytes:,} bytes "
        f"downloaded, {unpacked:,} unpacked, {len(names):,} packages / {versions:,} versions -> {path} "
        f"({path.stat().st_size:,} bytes)")
    return index


_lock = threading.Lock()  # guards _loaded / _failed
_build_lock = threading.Lock()  # one build at a time; current() never waits on it
_loaded: PackageIndex | None = None  # the last one used (one game's at a time)
_failed: dict[str, float] = {}  # index path -> env.clock() of its last failed build


def _discard(path: Path, why: str) -> None:
    log(f"[index] {path}: {why} - discarded")
    try:
        path.unlink(missing_ok=True)
    except OSError as err:
        log(f"[index] {path}: couldn't delete it ({err!r})")


def current(app_root, community: str, max_age_s: float = TTL_S) -> PackageIndex | None:
    """The index of `community` from memory, else from disk, when it is at
    most `max_age_s` old (TTL_S: dependency lookups; UPDATE_MAX_AGE_S: the
    update check); None when there is none (the caller falls back to
    per-package lookups). Never the network, never raises."""
    global _loaded
    path = index_path(app_root)
    with _lock:
        if _loaded is not None and _loaded.path == path:
            if _loaded.broken:
                _discard(path, "a corrupt entry")
                _loaded = None
            elif _loaded.community == community:  # the file on disk is this same one (build() replaces both)
                return _loaded if _loaded.fresh(max_age_s) else None
        try:
            st = path.stat()
        except OSError:
            return None
        if st.st_size > FILE_MAX_BYTES:
            _discard(path, f"{st.st_size:,} bytes, over the {FILE_MAX_BYTES >> 20} MB cap")
            return None
        if not 0 <= env.clock() - st.st_mtime < max_age_s + 3600:  # clearly stale: not even read (a build replaces it)
            return None
        try:
            index = PackageIndex(path.read_bytes(), path)
        except (OSError, zipfile.BadZipFile, ValueError, UnicodeDecodeError) as err:
            _discard(path, f"unreadable ({err!r})")
            return None
        if index.community != community or not index.fresh():
            return None
        _loaded = index  # kept even when too old for max_age_s: a TTL-fresh index still serves dependency lookups
        log(f"[index] {community}: loaded {path} ({index.packages} packages, "
            f"{(env.clock() - index.built_at) / 3600:.1f} h old)")
        return index if index.fresh(max_age_s) else None


def ensure(app_root, community: str, app_version=None, *, on_build=None, max_age_s: float = TTL_S) -> PackageIndex | None:
    """current(max_age_s), else a build (`on_build()` once it really starts
    downloading); None when that fails or failed less than RETRY_AFTER_S
    ago. Blocks while another job builds (then uses its result). For
    worker threads only; never raises."""
    global _loaded
    index = current(app_root, community, max_age_s)
    if index is not None:
        return index
    key = str(index_path(app_root))
    with _build_lock:
        index = current(app_root, community, max_age_s)  # another job's build may just have finished
        if index is not None:
            return index
        with _lock:
            since = env.clock() - _failed.get(key, float("-inf"))
        if since < RETRY_AFTER_S:
            log(f"[index] {community}: last build failed {since:.0f}s ago - per-package lookups this time")
            return None
        try:
            index = build(app_root, community, app_version, on_start=on_build)
        except Exception as err:  # noqa: BLE001 - the index is never required
            log(f"[index] {community}: build failed ({err!r}) - per-package lookups instead")
            with _lock:
                _failed[key] = env.clock()
            return None
        with _lock:
            _loaded = index
            _failed.pop(key, None)
        return index
