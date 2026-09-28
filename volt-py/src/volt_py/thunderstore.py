"""Thunderstore's keyless API + the shared package cache (THUNDERSTORE.md §1,
§2). Game-agnostic: the per-package endpoint has no community in its URL, so
one client serves Valheim, Lethal Company, R.E.P.O. alike.

- fetch_package(namespace, name): GET /api/experimental/package/<ns>/<name>/
  -> the package's metadata (latest.version_number / download_url /
  dependencies, date_updated, ...). This is the only listing endpoint used;
  the bulk /api/v1/package/ dump is deliberately NOT called here (tens of MB,
  unpaginated - the mod browser's catalog cache, stage 3f, is its own thing).
- download(url, dest): streams a package zip to disk atomically.
- ensure_cached(app_root, ref, download_url): the shared package cache,
  <APP-ROOT>/cache/packages/<Team-Package-Version>.zip - one download per
  package version, shared by every load order of that game (never per load
  order).
- PackageRef: "Team-Package[-Version]" parsing. Thunderstore namespaces and
  package names are [A-Za-z0-9_] only (no hyphens), so the string splits
  unambiguously from the right.
- version_key / is_newer: semver ordering for the update check (THUNDERSTORE.md
  §3): "2.31.0" is newer than "2.30.2", "5.4.2351" than "5.4.2333".
- read_meta_cache / write_meta_cache: <APP-ROOT>/cache/package-meta.json -
  what the last update check learned per package (latest version,
  date_updated, checked_at), keyed by full_name, so the manager's rows show
  a last-updated date before (or without) this run's check.

Pure Python, no Qt; urllib through the `env` seam (steam_web_api.py's
pattern) so tools/checks/volt_py_thunderstore.py can fake the replies. Same
known limitation as every other direct fetch in the app: no system/PAC proxy.
A failed request is a ThunderstoreError with a user-facing message; a bad
argument (not a package name) is a ValueError. Every request and its outcome
lands in volt.log (CLAUDE.md §10).
"""

import http.client
import json
import os
import re
import shutil
import types
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import net
from .applog import clip, log

SITE = "https://thunderstore.io"
TIMEOUT_S = 15.0  # metadata requests
DOWNLOAD_TIMEOUT_S = 60.0  # per socket operation while streaming a zip, not the whole transfer
CACHE_DIR = "cache"  # <APP-ROOT>/cache/ - also where 3f's catalog cache will go
PACKAGES_DIR = "packages"  # <APP-ROOT>/cache/packages/<Team-Package-Version>.zip
META_FILE = "package-meta.json"  # <APP-ROOT>/cache/package-meta.json (read_meta_cache)
_CHUNK = 1 << 16

_NAME = re.compile(r"[A-Za-z0-9_]+", re.ASCII)
_VERSION = re.compile(r"\d+\.\d+\.\d+", re.ASCII)

# Check-harness seam (no network in the sandbox).
env = types.SimpleNamespace(urlopen=net.urlopen)


class ThunderstoreError(RuntimeError):
    """A request to thunderstore.io failed; str() is a user-facing message."""


@dataclass(frozen=True)
class PackageRef:
    """A Thunderstore package: namespace (team) + name, optionally pinned to a
    version. full_name = "Team-Package" (the identity every list/manifest
    keys on); key = "Team-Package-Version" (the cache key)."""

    namespace: str
    name: str
    version: str | None = None

    def __post_init__(self):
        if not (isinstance(self.namespace, str) and _NAME.fullmatch(self.namespace)):
            raise ValueError(f"Not a Thunderstore namespace: {self.namespace!r}")
        if not (isinstance(self.name, str) and _NAME.fullmatch(self.name)):
            raise ValueError(f"Not a Thunderstore package name: {self.name!r}")
        if self.version is not None and not (isinstance(self.version, str) and _VERSION.fullmatch(self.version)):
            raise ValueError(f"Not a package version (major.minor.patch): {self.version!r}")

    @property
    def full_name(self) -> str:
        return f"{self.namespace}-{self.name}"

    @property
    def key(self) -> str:
        if self.version is None:
            raise ValueError(f"{self.full_name} has no version")
        return f"{self.full_name}-{self.version}"

    def with_version(self, version: str) -> "PackageRef":
        return PackageRef(self.namespace, self.name, version)

    @classmethod
    def parse(cls, value) -> "PackageRef":
        """"Team-Package" or "Team-Package-Version" (a manifest dependency
        string). ValueError for anything else."""
        s = value.strip() if isinstance(value, str) else ""
        parts = s.split("-")
        if len(parts) == 2:
            return cls(parts[0], parts[1])
        if len(parts) == 3:
            return cls(parts[0], parts[1], parts[2])
        raise ValueError(f"Not a Thunderstore package reference (Team-Package[-Version]): {value!r}")


def version_key(version: str) -> tuple:
    """A sortable key for "major.minor.patch": the three ints; anything that
    isn't that shape sorts below every real version (as (-1,))."""
    if isinstance(version, str) and _VERSION.fullmatch(version):
        return tuple(int(x) for x in version.split("."))
    return (-1,)


def is_newer(candidate: str, installed: str) -> bool:
    """True if `candidate` is a strictly newer semver than `installed`."""
    return version_key(candidate) > version_key(installed)


def package_url(namespace: str, name: str) -> str:
    return f"{SITE}/api/experimental/package/{namespace}/{name}/"


def download_url(ref: PackageRef) -> str:
    """The canonical zip URL for one version - what the API's
    latest.download_url follows too."""
    return f"{SITE}/package/download/{ref.namespace}/{ref.name}/{ref.version}/"


def _request(url: str, app_version=None) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={"User-Agent": f"VOLT/{app_version or '?'} Thunderstore client", "Accept": "*/*"},
        method="GET",
    )


def _reason(err: BaseException) -> str:
    return str(getattr(err, "reason", None) or str(err) or repr(err))


def fetch_package(namespace: str, name: str, app_version=None) -> dict:
    """Package metadata (the experimental per-package endpoint). Raises
    ThunderstoreError on HTTP/network/shape failure."""
    ref = PackageRef(namespace, name)  # validates
    url = package_url(ref.namespace, ref.name)
    log(f"[thunderstore] GET {url} (timeout {TIMEOUT_S:g}s)")
    try:
        with env.urlopen(_request(url, app_version), timeout=TIMEOUT_S) as res:
            status, body = getattr(res, "status", 200), res.read()
    except urllib.error.HTTPError as err:
        log(f"[thunderstore] {ref.full_name}: HTTP {err.code}")
        if err.code == 404:
            raise ThunderstoreError(f"Thunderstore has no package called {ref.full_name}.") from err
        raise ThunderstoreError(f"Thunderstore returned HTTP {err.code} for {ref.full_name}.") from err
    except (OSError, http.client.HTTPException) as err:
        log(f"[thunderstore] {ref.full_name}: request failed: {err!r}")
        raise ThunderstoreError(
            f"Couldn't reach Thunderstore ({_reason(err)}). Check your internet connection."
        ) from err
    log(f"[thunderstore] {ref.full_name}: HTTP {status}, {len(body)} bytes")
    if not 200 <= status < 300:
        raise ThunderstoreError(f"Thunderstore returned HTTP {status} for {ref.full_name}.")
    try:
        meta = json.loads(body.decode("utf-8-sig", errors="replace"))
    except ValueError as err:
        log(f"[thunderstore] {ref.full_name}: reply isn't JSON: {err} - {clip(body[:200])}")
        raise ThunderstoreError(f"Thunderstore sent a reply VOLT couldn't read ({ref.full_name}).") from err
    latest = meta.get("latest") if isinstance(meta, dict) else None
    if not isinstance(latest, dict) or not isinstance(latest.get("version_number"), str):
        log(f"[thunderstore] {ref.full_name}: reply has no latest.version_number: {clip(meta)}")
        raise ThunderstoreError(f"Thunderstore sent an unexpected reply for {ref.full_name}.")
    log(
        f"[thunderstore] {ref.full_name}: latest {latest['version_number']}, updated {meta.get('date_updated')}, "
        f"{len(latest.get('dependencies') or [])} deps"
    )
    return meta


def latest_ref(meta: dict) -> PackageRef:
    """The PackageRef of a fetch_package() reply's latest version."""
    return PackageRef(str(meta.get("namespace")), str(meta.get("name")), str(meta["latest"]["version_number"]))


def download(url: str, dest, app_version=None) -> Path:
    """Streams `url` to `dest` (temp sibling + os.replace, so a dropped
    connection never leaves a half-written file at `dest`). Returns `dest`."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.part")
    log(f"[thunderstore] download {url} -> {dest}")
    try:
        with env.urlopen(_request(url, app_version), timeout=DOWNLOAD_TIMEOUT_S) as res, open(tmp, "wb") as f:
            status = getattr(res, "status", 200)
            if not 200 <= status < 300:
                raise ThunderstoreError(f"Thunderstore returned HTTP {status} for {url}.")
            shutil.copyfileobj(res, f, _CHUNK)
            size = f.tell()
        os.replace(tmp, dest)
    except urllib.error.HTTPError as err:
        log(f"[thunderstore] download failed: HTTP {err.code} for {url}")
        raise ThunderstoreError(f"Thunderstore returned HTTP {err.code} downloading {url}.") from err
    except (OSError, http.client.HTTPException) as err:
        log(f"[thunderstore] download failed: {err!r} for {url}")
        raise ThunderstoreError(f"Couldn't download from Thunderstore ({_reason(err)}).") from err
    finally:
        tmp.unlink(missing_ok=True)
    log(f"[thunderstore] downloaded {size} bytes -> {dest}")
    return dest


def package_cache_dir(app_root) -> Path:
    return Path(app_root) / CACHE_DIR / PACKAGES_DIR


def cached_package(app_root, ref: PackageRef) -> Path | None:
    """The cached zip for this exact version, or None."""
    p = package_cache_dir(app_root) / f"{ref.key}.zip"
    return p if p.is_file() else None


def ensure_cached(app_root, ref: PackageRef, url: str | None = None, app_version=None) -> Path:
    """The cached zip for `ref` (a versioned PackageRef), downloading it into
    the shared cache first if it isn't there yet. `url` defaults to the
    canonical download URL for that version."""
    p = package_cache_dir(app_root) / f"{ref.key}.zip"
    if p.is_file():
        log(f"[thunderstore] cache hit {ref.key} ({p.stat().st_size} bytes)")
        return p
    return download(url or download_url(ref), p, app_version)


def evict_cached(app_root, ref: PackageRef) -> bool:
    """Drops one cached zip (a corrupt download); True if there was one."""
    p = package_cache_dir(app_root) / f"{ref.key}.zip"
    try:
        p.unlink()
    except FileNotFoundError:
        return False
    log(f"[thunderstore] evicted {p}")
    return True


def meta_cache_path(app_root) -> Path:
    return Path(app_root) / CACHE_DIR / META_FILE


def read_meta_cache(app_root) -> dict[str, dict]:
    """full_name -> {"latest_version", "date_updated", "checked_at"} from the
    last update check; {} when there is none or it can't be read."""
    try:
        with open(meta_cache_path(app_root), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, dict)}


def write_meta_cache(app_root, cache: dict[str, dict]) -> None:
    """Replaces the cache file (temp sibling + os.replace). A failure is
    logged, never raised: the cache is a convenience, not state."""
    p = meta_cache_path(app_root)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.part")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except OSError as err:
        log(f"[thunderstore] meta cache write failed: {err!r}")
