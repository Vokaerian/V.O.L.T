"""The mod browser's data layer (THUNDERSTORE.md §5, Option B - paged,
decided 2026-09-28): the small per-page listing calls thunderstore.io's own
site makes, plus the per-package detail pieces the Package Detail view
shows. Game-agnostic: only the community slug in the URL changes per game.

**Undocumented endpoints live here and nowhere else.** The `/api/cyberstorm/`
calls below are what thunderstore.io's frontend uses today, not part of its
documented public API, so every reply is shape-checked and a mismatch is a
ThunderstoreError with a user-facing "the browser needs an update" message -
the browser shows it, nothing else in the app touches this module. Verified
against the live site 2026-09-28 (the handoff has the probes):

- GET /api/cyberstorm/listing/<community>/?q=&ordering=&page=&included_categories=
  &deprecated=False&nsfw=False -> {count, next, previous, results: [{namespace,
  name, description, icon_url, download_count, rating_count, last_updated,
  categories: [{id, name, slug}], size, is_pinned, is_deprecated, is_nsfw,
  datetime_created, community_identifier}]}. Always 20 results per page
  (PAGE_SIZE; a page_size parameter is ignored), page past the end = HTTP
  404 {"detail": "Invalid page."}, a bad ordering = HTTP 400. Orderings:
  ORDERINGS. `included_categories` takes a category *id* (a slug is a 400).
  Without deprecated / nsfw the site's own defaults are False (the `next`
  URL echoes them) - passed explicitly anyway. deprecated=True / nsfw=True
  INCLUDE those packages alongside the rest (not "only them"; probed
  2026-09-29: Valheim most-downloaded counts 6740 False/False, 12121
  True/False, 6776 False/True, 12201 True/True) - the browser's "Show
  deprecated" / "Show NSFW" toggles.
- GET /api/cyberstorm/community/<community>/filters/ -> {package_categories:
  [{id, name, slug}], sections: [...]}.
- GET /api/cyberstorm/listing/<community>/<ns>/<name>/ -> the package's
  listing detail (the detail page's right column, always the latest
  version): dependencies: [{namespace, name, version_number, description,
  icon_url, is_active}], download_count, rating_count, size, website_url,
  latest_version_number, full_version_name, version_created (last
  updated), package_created (first uploaded), dependant_count,
  has_changelog, categories, description, icon_url, version_count,
  is_deprecated.
- GET /api/cyberstorm/package/<ns>/<name>/versions/ -> [{version_number,
  datetime_created, download_count, download_url}] (unsorted; sorted here).
The documented experimental endpoints used alongside:
- GET /api/experimental/package/<ns>/<name>/<version>/ -> that version's
  {version_number, dependencies, description, website_url, icon, ...}
  (thunderstore.fetch_package's shape, one level up).
- GET /api/experimental/package/<ns>/<name>/<version>/readme/ -> {markdown}.
- GET /api/experimental/package/<ns>/<name>/<version>/changelog/ ->
  {markdown} (null when the version has none).
- GET /api/experimental/package/<ns>/<name>/wiki/ -> {id, title, slug,
  datetime_created, datetime_updated, pages: [{id, title, slug,
  datetime_created, datetime_updated}]} (ids are strings; HTTP 404
  {"detail": "Not found."} when the package has no wiki), and
  GET /api/experimental/wiki/page/<id>/ -> {id, title, slug, datetime_created,
  datetime_updated, markdown_content} (verified live 2026-09-30 against
  RandyKnapp-EpicLoot: 8 pages "1. What is Epic Loot" .. "8. Cheats/Commands",
  API order = the numbering; an unknown page id is a 404). The Wiki tab
  orders the pages with order_wiki_pages.
README / changelog / wiki images (0.6.31): image_urls picks the http(s) image
links out of the markdown (the first IMAGE_LIMIT) and load_images fetches
them in the background, FETCH_WORKERS at once in list order: the disk cache
first (<APP-ROOT>/cache/readme-images/<sha256 of the URL>, no network on a
hit), badge hosts (BADGE_HOSTS) skipped outright, IMAGE_TIMEOUT_S per socket
operation, a size cap each, and an IMAGE_BUDGET_S budget per page after which
nothing new starts (what is in flight finishes and is kept); each image is
handed back as it lands (on_image), so the window's text browser fills in
while the page is already up - still no browser-side network. A fetched image
goes through the window's shrinker first (at most 1600 px wide, re-encoded;
web-page / text replies are never kept), and prune_image_cache holds the
folder under IMAGE_CACHE_CAP (least recently used first) each time a Browse
Mods window opens; Settings' Clean up downloads empties it.

Also here: PagedListing - the browser's own pages over that stream, every
one PAGE_SIZE long with the pinned packages taken out (the site's page 1
holds them, so its pages and VOLT's pages drift by that many; the class
tops a page up from the next site page and keeps the offsets consistent);
dependency_chain (which of a package's dependencies the open load
order already has, which get pulled in - recursively, at Thunderstore's
latest, THUNDERSTORE.md §1 / §9's policy - so the detail view's Install
button can say "+ N dependencies") and parallel_dependency_chain (the same
answer, its package metadata fetched level by level FETCH_WORKERS at once
first), fetch_bytes for the card icons (ccdn.
thunderstore.io), and the number formatting the cards use.

Pure Python, no Qt; every request goes through thunderstore.env.urlopen (the
harness seam) with the same User-Agent. tools/checks/volt_py_thunderstore_
browse.py fakes the site; tools/checks/volt_py_browse_perf.py the background
image / dependency-chain loading (0.6.31).
"""

import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
from collections import Counter
from pathlib import Path
from . import thunderstore as ts
from .applog import clip, log
from .thunderstore import ThunderstoreError

SITE_PAGE_SIZE = 20  # the site's fixed page size (verified 2026-09-28: page_size is ignored)
PAGE_SIZE = 16  # VOLT's page: 4 columns x 4 rows (user, 2026-09-29; was 20)
DEFAULT_ORDERING = "last-updated"
# (query value, label) - the site's own choices; anything else is an HTTP 400.
ORDERINGS = (
    ("last-updated", "Last updated"),
    ("most-downloaded", "Most downloaded"),
    ("top-rated", "Top rated"),
    ("newest", "Newest"),
)
ICON_MAX_BYTES = 2 << 20  # a 256x256 PNG is ~100 KB; anything bigger isn't an icon
IMAGE_MAX_BYTES = 6 << 20  # a README screenshot; a bigger one is skipped
IMAGE_LIMIT = 24  # images fetched per README / changelog, in order of appearance
# ![alt](url "title") and <img src="url"> - the two ways a README carries an image.
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^\s)>]+)>?(?:\s+\"[^\"]*\")?\s*\)|<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
CHAIN_LIMIT = 40  # dependency_chain stops resolving past this many packages (a runaway graph)
# dependency_chain's problems entry at the cut-off (the window shows it as a note, not as a problem)
CHAIN_LIMIT_MESSAGE = f"more than {CHAIN_LIMIT} dependencies; the rest aren't listed here"
FETCH_WORKERS = 6  # load_images / parallel_dependency_chain: requests at once (0.6.31; were one at a time)
IMAGE_TIMEOUT_S = 8.0  # per socket operation for a README image (the API calls keep thunderstore.TIMEOUT_S)
IMAGE_BUDGET_S = 20.0  # per page: no new image fetch starts after this; the queue is abandoned
IMAGE_CACHE_DIR = "readme-images"  # <APP-ROOT>/cache/readme-images/<sha256 of the URL>
IMAGE_CACHE_CAP = 100 << 20  # prune_image_cache: over this when a Browse Mods window opens ...
IMAGE_CACHE_TARGET = 80 << 20  # ... the least recently used files go until it's under this
IMAGE_KEEP_RAW_MAX = 1 << 20  # an image the shrinker can't decode is cached as is only below this size
# Badge services: a README's build / version / download-count badges - tiny, often slow (img.shields.io
# answered HTTP 408 after ~8 s in the 0.6.31 log), never worth a fetch. Skipped, they stay blank boxes.
BADGE_HOSTS = ("img.shields.io", "badgen.net", "forthebadge.com", "badge.fury.io", "badges.gitter.im")
SHAPE_MESSAGE = "Thunderstore's mod listing has changed shape; VOLT's mod browser needs an update."


def listing_url(community: str, *, query: str = "", ordering: str = DEFAULT_ORDERING, category=None, page: int = 1,
                deprecated: bool = False, nsfw: bool = False) -> str:
    params = {"ordering": ordering, "page": page, "deprecated": str(bool(deprecated)), "nsfw": str(bool(nsfw))}
    if query:
        params["q"] = query
    if category:
        params["included_categories"] = category
    return f"{ts.SITE}/api/cyberstorm/listing/{community}/?{urllib.parse.urlencode(params)}"


def filters_url(community: str) -> str:
    return f"{ts.SITE}/api/cyberstorm/community/{community}/filters/"


def listing_detail_url(community: str, namespace: str, name: str) -> str:
    return f"{ts.SITE}/api/cyberstorm/listing/{community}/{namespace}/{name}/"


def versions_url(namespace: str, name: str) -> str:
    return f"{ts.SITE}/api/cyberstorm/package/{namespace}/{name}/versions/"


def version_url(namespace: str, name: str, version: str) -> str:
    return f"{ts.SITE}/api/experimental/package/{namespace}/{name}/{version}/"


def readme_url(namespace: str, name: str, version: str) -> str:
    return f"{ts.SITE}/api/experimental/package/{namespace}/{name}/{version}/readme/"


def changelog_url(namespace: str, name: str, version: str) -> str:
    return f"{ts.SITE}/api/experimental/package/{namespace}/{name}/{version}/changelog/"


def wiki_url(namespace: str, name: str) -> str:
    return f"{ts.SITE}/api/experimental/package/{namespace}/{name}/wiki/"


def wiki_page_url(page_id) -> str:
    return f"{ts.SITE}/api/experimental/wiki/page/{urllib.parse.quote(str(page_id), safe='')}/"


def team_page_url(community: str, namespace: str) -> str:
    """The author's page on the site (the header's author link)."""
    return f"{ts.SITE}/c/{community}/p/{namespace}/"


def dependants_page_url(community: str, namespace: str, name: str) -> str:
    """The site's "other mods that depend on this" page (the right column's Dependants link)."""
    return f"{ts.SITE}/c/{community}/p/{namespace}/{name}/dependants/"


def _get(url: str, app_version, what: str, *, max_bytes: int | None = None, timeout: float | None = None) -> bytes:
    """One GET through the env seam; HTTP / network failures are
    ThunderstoreErrors with user-facing text (`what` names the thing).
    `timeout`: per socket operation, thunderstore.TIMEOUT_S by default."""
    log(f"[browse] GET {url}" + (f" (timeout {timeout:g}s)" if timeout else ""))
    try:
        with ts.open_url(ts._request(url, app_version), timeout or ts.TIMEOUT_S) as res:  # HTTP 429 retried there
            status = getattr(res, "status", 200)
            body = res.read(max_bytes + 1) if max_bytes else res.read()
    except urllib.error.HTTPError as err:
        log(f"[browse] {what}: HTTP {err.code}")
        if err.code == 404:
            raise ThunderstoreError(f"Thunderstore has no {what}.") from err
        raise ThunderstoreError(f"Thunderstore returned HTTP {err.code} for the {what}.") from err
    except (OSError, http.client.HTTPException) as err:
        log(f"[browse] {what}: request failed: {err!r}")
        raise ThunderstoreError(
            f"Couldn't reach Thunderstore ({ts._reason(err)}). Check your internet connection."
        ) from err
    log(f"[browse] {what}: HTTP {status}, {len(body)} bytes")
    if not 200 <= status < 300:
        raise ThunderstoreError(f"Thunderstore returned HTTP {status} for the {what}.")
    if max_bytes and len(body) > max_bytes:
        raise ThunderstoreError(f"Thunderstore's {what} is larger than expected ({len(body)} bytes).")
    return body


def _get_json(url: str, app_version, what: str):
    body = _get(url, app_version, what)
    try:
        return json.loads(body.decode("utf-8-sig", errors="replace"))
    except ValueError as err:
        log(f"[browse] {what}: reply isn't JSON: {err} - {clip(body[:200])}")
        raise ThunderstoreError(f"Thunderstore sent a reply VOLT couldn't read ({what}).") from err


def _shape_error(what: str, detail: str, data=None) -> ThunderstoreError:
    log(f"[browse] {what}: unexpected shape ({detail}): {clip(data)}")
    return ThunderstoreError(f"{SHAPE_MESSAGE} ({what}: {detail})")


def _str(d: dict, key: str, default: str = "") -> str:
    v = d.get(key)
    return v if isinstance(v, str) else default


def _int(d: dict, key: str, default: int = 0) -> int:
    v = d.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _listing(item, what: str) -> dict:
    """One listing result, normalized to what the cards / detail use."""
    if not isinstance(item, dict):
        raise _shape_error(what, "a result isn't an object", item)
    ns, name = item.get("namespace"), item.get("name")
    if not (isinstance(ns, str) and isinstance(name, str) and ns and name):
        raise _shape_error(what, "a result has no namespace / name", item)
    cats = item.get("categories")
    categories = [c["name"] for c in cats if isinstance(c, dict) and isinstance(c.get("name"), str)] if isinstance(cats, list) else []
    return {
        "namespace": ns,
        "name": name,
        "full_name": f"{ns}-{name}",
        "description": _str(item, "description"),
        "icon_url": _str(item, "icon_url"),
        "download_count": _int(item, "download_count"),
        "rating_count": _int(item, "rating_count"),
        "last_updated": _str(item, "last_updated"),
        "categories": categories,
        "size": _int(item, "size"),
        "is_pinned": bool(item.get("is_pinned", False)),
        "is_deprecated": bool(item.get("is_deprecated", False)),
        "is_nsfw": bool(item.get("is_nsfw", False)),
    }


def list_packages(community: str, *, query: str = "", ordering: str = DEFAULT_ORDERING, category=None,
                  page: int = 1, deprecated: bool = False, nsfw: bool = False, app_version=None) -> dict:
    """One page of the SITE's listing: {"count": total matching packages
    (pinned ones included - the site counts them), "pages": total site
    pages, "page": this page, "results": [listing dicts, pinned packages
    left out - the framework pack / r2modman aren't browsable mods],
    "pinned": how many were left out, "last": whether the site has no
    page after this one}. A page past the end is a ThunderstoreError (the
    site's 404), as is any shape change. The browser pages through
    PagedListing, not this directly."""
    if ordering not in dict(ORDERINGS):
        raise ValueError(f"Not a listing ordering: {ordering!r}")
    if not isinstance(page, int) or page < 1:
        raise ValueError(f"Not a page number: {page!r}")
    what = f"mod listing (page {page})"
    data = _get_json(listing_url(community, query=query, ordering=ordering, category=category, page=page,
                                 deprecated=deprecated, nsfw=nsfw), app_version, what)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise _shape_error(what, "no results list", data)
    count = _int(data, "count", -1)
    if count < 0:
        raise _shape_error(what, "no count", data)
    results = [_listing(item, what) for item in data["results"]]
    shown = [r for r in results if not r["is_pinned"]]
    pages = max(1, -(-count // SITE_PAGE_SIZE))
    log(f"[browse] listing page {page}/{pages}: {len(results)} results ({len(results) - len(shown)} pinned hidden), "
        f"{count} total, q={query!r}, ordering={ordering}, category={category}, deprecated={deprecated}, nsfw={nsfw}")
    return {"count": count, "pages": pages, "page": page, "results": shown, "pinned": len(results) - len(shown),
            "last": page >= pages}


class PagedListing:
    """One search (community + query + ordering + category + the deprecated /
    nsfw include flags) as VOLT's pages:
    every page PAGE_SIZE (16) listings long with the pinned packages
    removed, filled from as many SITE_PAGE_SIZE (20) site pages as it takes
    (each fetched once and kept: VOLT's page 1 = site page 1, page 2 =
    site pages 1-2, page 3 = 1-3, ...). page(n) -> {"page", "pages",
    "count" (browsable packages, the site's count minus the pinned seen),
    "results"}; n past the end returns no results with the real page
    count. Network happens inside page() - call it off the GUI thread;
    the lock keeps overlapping calls (a fast Next, Next) consistent."""

    def __init__(self, community: str, *, query: str = "", ordering: str = DEFAULT_ORDERING, category=None,
                 deprecated: bool = False, nsfw: bool = False, app_version=None) -> None:
        self.community, self.query, self.ordering, self.category, self.app_version = community, query, ordering, category, app_version
        self.deprecated, self.nsfw = deprecated, nsfw
        self._items: list[dict] = []  # every browsable listing fetched so far, in the site's order
        self._site_pages = 0  # how many site pages are in _items
        self._count = 0  # the site's count (pinned included)
        self._pinned = 0  # pinned packages seen (and dropped) so far
        self._exhausted = False  # the site has no page after _site_pages
        self._lock = threading.Lock()

    @property
    def pages(self) -> int:
        return max(1, -(-max(0, self._count - self._pinned) // PAGE_SIZE))

    def _fetch_next_site_page(self) -> None:
        res = list_packages(self.community, query=self.query, ordering=self.ordering, category=self.category,
                            page=self._site_pages + 1, deprecated=self.deprecated, nsfw=self.nsfw,
                            app_version=self.app_version)
        self._site_pages = res["page"]
        self._count = res["count"]
        self._pinned += res["pinned"]
        self._items.extend(res["results"])
        self._exhausted = res["last"]

    def page(self, n: int) -> dict:
        if not isinstance(n, int) or n < 1:
            raise ValueError(f"Not a page number: {n!r}")
        with self._lock:
            need = n * PAGE_SIZE
            while len(self._items) < need and not self._exhausted:
                self._fetch_next_site_page()
            start = (n - 1) * PAGE_SIZE
            results = self._items[start:start + PAGE_SIZE]
            log(f"[browse] VOLT page {n}/{self.pages}: {len(results)} listings from {self._site_pages} site pages "
                f"({self._pinned} pinned dropped, {self._count} counted)")
            return {"page": n, "pages": self.pages, "count": max(0, self._count - self._pinned), "results": results}


def list_categories(community: str, app_version=None) -> list[dict]:
    """The community's package categories: [{id, name, slug}] in the site's
    order (id is what list_packages' `category` takes)."""
    what = "category list"
    data = _get_json(filters_url(community), app_version, what)
    cats = data.get("package_categories") if isinstance(data, dict) else None
    if not isinstance(cats, list):
        raise _shape_error(what, "no package_categories", data)
    out = []
    for c in cats:
        if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("id") is not None:
            out.append({"id": str(c["id"]), "name": c["name"], "slug": _str(c, "slug")})
    log(f"[browse] {len(out)} categories for {community}")
    return out


def fetch_listing_detail(community: str, namespace: str, name: str, app_version=None) -> dict:
    """The Package Detail view's header numbers + the latest version's direct
    dependencies: {namespace, name, full_name, description, icon_url,
    download_count, rating_count, size, website_url, latest_version,
    is_deprecated, dependencies: [{namespace, name, full_name, version_number, description}]}."""
    ref = ts.PackageRef(namespace, name)  # validates
    what = f"package page for {ref.full_name}"
    data = _get_json(listing_detail_url(community, ref.namespace, ref.name), app_version, what)
    if not isinstance(data, dict) or not isinstance(data.get("latest_version_number"), str):
        raise _shape_error(what, "no latest_version_number", data)
    deps_raw = data.get("dependencies")
    if not isinstance(deps_raw, list):
        raise _shape_error(what, "no dependencies list", data)
    deps = []
    for d in deps_raw:
        if isinstance(d, dict) and isinstance(d.get("namespace"), str) and isinstance(d.get("name"), str):
            deps.append({
                "namespace": d["namespace"], "name": d["name"], "full_name": f"{d['namespace']}-{d['name']}",
                "version_number": _str(d, "version_number"), "description": _str(d, "description"),
                "icon_url": _str(d, "icon_url"),
            })
    cats = data.get("categories")
    categories = ([{"id": str(c["id"]), "name": c["name"]} for c in cats
                   if isinstance(c, dict) and isinstance(c.get("name"), str) and c.get("id") is not None]
                  if isinstance(cats, list) else [])
    detail = {
        "namespace": ref.namespace, "name": ref.name, "full_name": ref.full_name,
        "description": _str(data, "description"), "icon_url": _str(data, "icon_url"),
        "download_count": _int(data, "download_count"), "rating_count": _int(data, "rating_count"),
        "size": _int(data, "size"), "website_url": _str(data, "website_url"),
        "latest_version": data["latest_version_number"], "dependencies": deps,
        "full_version_name": _str(data, "full_version_name") or f"{ref.full_name}-{data['latest_version_number']}",
        "last_updated": _str(data, "version_created"), "first_uploaded": _str(data, "package_created"),
        "dependant_count": _int(data, "dependant_count"), "has_changelog": bool(data.get("has_changelog", False)),
        "categories": categories, "version_count": _int(data, "version_count"),
        "is_deprecated": bool(data.get("is_deprecated", False)),
    }
    log(f"[browse] {ref.full_name}: latest {detail['latest_version']}, {len(deps)} direct deps, "
        f"{detail['download_count']} downloads")
    return detail


def fetch_versions(namespace: str, name: str, app_version=None) -> list[dict]:
    """Every published version of the package, newest first (semver order -
    the site's own list isn't sorted): [{version, created, downloads}]."""
    ref = ts.PackageRef(namespace, name)
    what = f"version list for {ref.full_name}"
    data = _get_json(versions_url(ref.namespace, ref.name), app_version, what)
    if not isinstance(data, list):
        raise _shape_error(what, "not a list", data)
    rows: dict[str, dict] = {}
    for v in data:
        if isinstance(v, dict) and isinstance(v.get("version_number"), str):
            rows[v["version_number"]] = {"version": v["version_number"], "created": _str(v, "datetime_created"),
                                         "downloads": _int(v, "download_count")}
    if not rows:
        raise _shape_error(what, "no version_number entries", data)
    versions = sorted(rows.values(), key=lambda r: ts.version_key(r["version"]), reverse=True)
    log(f"[browse] {ref.full_name}: {len(versions)} versions, latest {versions[0]['version']}")
    return versions


def fetch_version(namespace: str, name: str, version: str, app_version=None) -> dict:
    """One version's metadata (the documented experimental endpoint):
    {version, dependencies: ["Team-Package-Version", ...], description,
    website_url, icon}."""
    ref = ts.PackageRef(namespace, name, version)
    what = f"version {version} of {ref.full_name}"
    data = _get_json(version_url(ref.namespace, ref.name, ref.version), app_version, what)
    if not isinstance(data, dict) or not isinstance(data.get("version_number"), str):
        raise _shape_error(what, "no version_number", data)
    deps = data.get("dependencies")
    deps = [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
    return {"version": data["version_number"], "dependencies": deps, "description": _str(data, "description"),
            "website_url": _str(data, "website_url"), "icon": _str(data, "icon")}


def fetch_readme(namespace: str, name: str, version: str, app_version=None) -> str:
    """The version's README as markdown ("" when the package has none)."""
    ref = ts.PackageRef(namespace, name, version)
    what = f"README of {ref.full_name} {version}"
    data = _get_json(readme_url(ref.namespace, ref.name, ref.version), app_version, what)
    md = data.get("markdown") if isinstance(data, dict) else None
    if not isinstance(md, str):
        raise _shape_error(what, "no markdown", data)
    return md


def fetch_changelog(namespace: str, name: str, version: str, app_version=None) -> str:
    """The version's changelog as markdown ("" when it has none - the site's
    null)."""
    ref = ts.PackageRef(namespace, name, version)
    what = f"changelog of {ref.full_name} {version}"
    data = _get_json(changelog_url(ref.namespace, ref.name, ref.version), app_version, what)
    if not isinstance(data, dict) or "markdown" not in data:
        raise _shape_error(what, "no markdown", data)
    md = data["markdown"]
    if md is not None and not isinstance(md, str):
        raise _shape_error(what, "markdown isn't text", data)
    return md or ""


def fetch_wiki_index(namespace: str, name: str, app_version=None) -> list[dict]:
    """The package's wiki pages [{id, title}] in the API's order ([] when the
    package has no wiki - the site's 404). Other failures raise."""
    ref = ts.PackageRef(namespace, name)
    what = f"wiki of {ref.full_name}"
    try:
        data = _get_json(wiki_url(ref.namespace, ref.name), app_version, what)
    except ThunderstoreError as err:
        cause = err.__cause__
        if isinstance(cause, urllib.error.HTTPError) and cause.code == 404:
            log(f"[browse] {what}: none")
            return []
        raise
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        raise _shape_error(what, "no pages", data)
    out = []
    for page in pages:
        if not (isinstance(page, dict) and isinstance(page.get("id"), (str, int)) and isinstance(page.get("title"), str)):
            raise _shape_error(what, "a page has no id / title", page)
        out.append({"id": str(page["id"]), "title": page["title"]})
    log(f"[browse] {what}: {len(out)} pages")
    return out


def fetch_wiki_page(page_id, app_version=None) -> str:
    """One wiki page's markdown ("" when the page is empty)."""
    what = f"wiki page {page_id}"
    data = _get_json(wiki_page_url(page_id), app_version, what)
    if not isinstance(data, dict) or "markdown_content" not in data:
        raise _shape_error(what, "no markdown_content", data)
    md = data["markdown_content"]
    if md is not None and not isinstance(md, str):
        raise _shape_error(what, "markdown_content isn't text", data)
    return md or ""


# Wiki page order (order_wiki_pages; the user's rule, 2026-09-30).
_WIKI_PINNED = {"index", "home"}
# "1." "2)" "01 -" "1.2 Title" "1.10" "Part 3": a number (dotted parts allowed) followed by
# punctuation, a space or the end - "3D Models" / "2x Speed" stay unprefixed.
_WIKI_NUMBER = re.compile(r"\s*(?:part\s*)?(\d+(?:\.\d+)*)\.?(?=[\s).:\-\u2013\u2014]|$)", re.IGNORECASE)
# "a." "b)" "C) Title": one letter, then "." or ")", then a space or the end.
_WIKI_LETTER = re.compile(r"\s*([a-z])[.)](?=\s|$)", re.IGNORECASE)


def _wiki_key(page: dict) -> tuple:
    title = page["title"].strip()
    tie = (title.casefold(), str(page["id"]))
    if title.casefold() in _WIKI_PINNED:
        return (0, (), "", *tie)
    m = _WIKI_NUMBER.match(title)
    if m:
        return (1, tuple(int(n) for n in m.group(1).split(".")), "", *tie)
    m = _WIKI_LETTER.match(title)
    if m:
        return (2, (), m.group(1).casefold(), *tie)
    return (3, (), "", *tie)


def order_wiki_pages(pages: list[dict]) -> list[dict]:
    """The Wiki tab's rail order (user rule, 2026-09-30): pages titled Index /
    Home (case-insensitive, exact) first; then numbered pages ("1.", "2)",
    "01 -", "1.2", "Part 3") in natural numeric order (1.2 < 1.10, "1." before
    "1.1"); then letter-sequenced pages ("a.", "b)") by the letter; then the
    rest alphabetically. Case-insensitive title, then the page id, breaks
    every tie (two "3." pages, "Part 3" vs "3.", Home vs Index), so the
    order never depends on the API's."""
    return sorted(pages, key=_wiki_key)


# HTML in a README (the markdown importer's weak spot): a line starting with
# one of these tags opens an HTML chunk that runs until every tag opened in
# it is closed again (void tags don't count). The window renders such chunks
# through Qt's HTML path and the rest through its markdown importer
# (split_html_blocks).
_HTML_BLOCK_START = re.compile(
    r"^\s{0,3}<(?:/?(?:div|p|h[1-6]|table|center|ul|ol|li|details|summary|img|a|br|hr|blockquote|pre|section|span|b|i|"
    r"strong|em|font|picture|video|iframe|figure|dl|dt|dd|sup|sub|small|code|kbd|u|s)\b|!--)",
    re.IGNORECASE)
_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)[^<>]*?(/?)>|<!--.*?-->", re.DOTALL)
_VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "area", "col", "embed", "param", "track"}


def _tag_depth_delta(line: str) -> int:
    """How many HTML elements a line opens minus how many it closes (void
    and self-closed tags and comments count for nothing)."""
    delta = 0
    for m in _TAG.finditer(line):
        if m.group(2) is None:  # a comment
            continue
        closing, name, selfclosed = m.group(1), m.group(2).lower(), m.group(3)
        if name in _VOID_TAGS or selfclosed:
            continue
        delta += -1 if closing else 1
    return delta


def split_html_blocks(markdown: str) -> list[tuple[str, str]]:
    """The markdown as [("md", text) | ("html", text), ...] in order: an
    "html" chunk starts at a line that begins with an HTML tag (a raw-HTML
    README: centered headings, styled divs, image rows) and runs until its
    tags balance at the end of a line - blank lines inside it don't end it,
    which is exactly where Qt's markdown importer loses the rest of such a
    README (an open <div> across a blank line, an <img> without a closing
    tag). Everything else stays markdown. An unclosed chunk runs to the end."""
    chunks: list[tuple[str, str]] = []
    kind, buf, depth = "md", [], 0

    def flush() -> None:
        text = "\n".join(buf)
        if text.strip():
            chunks.append((kind, text))
        buf.clear()

    for line in (markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if kind == "md":
            if _HTML_BLOCK_START.match(line):
                flush()
                kind = "html"
                depth = 0
            else:
                buf.append(line)
                continue
        buf.append(line)
        depth += _tag_depth_delta(line)
        if depth <= 0:
            flush()
            kind, depth = "md", 0
    flush()
    return chunks


# Qt's markdown importer (QTextMarkdownImporter::cbText) counts raw inline HTML
# naively: every "<letter" opens, every "</" or "/>" closes, and while the count
# is above zero all ordinary text is held back for an HTML insert that only
# happens when it's back to zero - code spans still go through. So one unclosed
# tag-like token ("**<rarity>**", "<effect count>", a bare "<br>") silently drops
# the rest of the chunk's prose (EpicLoot's wiki page "8. Cheats/Commands",
# found on hardware 2026-09-30). qt_markdown fixes the markdown before Qt sees it.
_KNOWN_TAGS = _VOID_TAGS | {
    "a", "abbr", "address", "article", "aside", "b", "big", "blockquote", "body", "center", "cite", "code", "dd", "del",
    "details", "dfn", "div", "dl", "dt", "em", "figcaption", "figure", "font", "footer", "h1", "h2", "h3", "h4", "h5",
    "h6", "head", "header", "html", "i", "iframe", "ins", "kbd", "li", "main", "mark", "nav", "nobr", "ol", "p", "picture",
    "pre", "q", "s", "samp", "section", "small", "span", "strike", "strong", "sub", "summary", "sup", "table", "tbody",
    "td", "tfoot", "th", "thead", "title", "tr", "tt", "u", "ul", "var", "video",
}
_INLINE_TAG = re.compile(r"(?<!\\)<(/?)([A-Za-z][A-Za-z0-9-]*)(\s[^<>]*?)?(/?)>")
_FENCE = re.compile(r"\s{0,3}(`{3,}|~{3,})")
_BACKTICKS = re.compile(r"`+")


def _qt_tag(m: re.Match) -> str:
    closing, name, _attrs, selfclosed = m.groups()
    if name.lower() not in _KNOWN_TAGS:
        return "\\" + m.group(0)  # "<rarity>" is text, not HTML: shown literally
    if name.lower() in _VOID_TAGS and not closing and not selfclosed:
        return m.group(0)[:-1] + "/>"  # "<br>" -> "<br/>": Qt's count sees it close
    return m.group(0)


def _qt_line(line: str) -> str:
    parts, pos, i = [], 0, 0
    while (run := _BACKTICKS.search(line, i)) is not None:  # code spans pass through untouched
        close = re.compile(rf"(?<!`){run.group(0)}(?!`)").search(line, run.end())
        if close is None:
            i = run.end()  # an unmatched run is literal backticks
            continue
        parts += [_INLINE_TAG.sub(_qt_tag, line[pos:run.start()]), line[run.start():close.end()]]
        pos = i = close.end()
    parts.append(_INLINE_TAG.sub(_qt_tag, line[pos:]))
    return "".join(parts)


def qt_markdown(markdown: str) -> str:
    """A markdown chunk made safe for Qt's importer (the comment above):
    outside code spans and fenced blocks, a tag-like token that isn't an HTML
    element is backslash-escaped (shown literally) and a void element is
    self-closed. Known elements are left as they are.
    ponytail: per line - a code span broken over two lines, an indented code
    block (an unknown tag in one shows a stray backslash) and an unclosed
    known element ("<b>" never closed) are not handled; a real markdown
    tokenizer if they show up."""
    out, fence = [], None
    for line in (markdown or "").split("\n"):
        m = _FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append(line)
        elif m:
            fence = m.group(1)
            out.append(line)
        else:
            out.append(_qt_line(line))
    return "\n".join(out)


def markdown_image_urls(markdown: str) -> list[str]:
    """The http(s) image URLs a markdown text references, in order, each once."""
    out: list[str] = []
    for m in _MD_IMAGE.finditer(markdown or ""):
        url = m.group(1) or m.group(2) or ""
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out


def image_urls(markdown: str, limit: int = IMAGE_LIMIT) -> list[str]:
    """The first `limit` image URLs of `markdown` (markdown_image_urls); the rest is logged, not fetched."""
    urls = markdown_image_urls(markdown)
    if len(urls) > limit:
        log(f"[browse] {len(urls) - limit} more images not fetched (limit {limit})")
    return urls[:limit]


def is_badge(url: str) -> bool:
    """A BADGE_HOSTS image (the host or a subdomain of it)."""
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in BADGE_HOSTS)


def image_cache_path(app_root, url: str) -> Path:
    return Path(app_root) / ts.CACHE_DIR / IMAGE_CACHE_DIR / hashlib.sha256(url.encode("utf-8")).hexdigest()


def _cache_image(path: Path, data: bytes) -> None:
    """mod_icons' write: a temp file, then replace - best effort, a failure only costs a refetch."""
    # ponytail: the IMAGE_CACHE_CAP is enforced when a Browse Mods window opens (prune_image_cache), so one
    # long session can run past it until the next open; prune after each page too if that ever matters.
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as err:
        log(f"[browse] image cache write failed for {path.name} ({err})")


def _is_text_body(data: bytes) -> bool:
    """A web page / JSON / text reply where an image was expected (a host's
    error page with HTTP 200): never shown, never cached. SVG is XML but an
    image, so it doesn't count."""
    head = data[:512].lstrip().lower()
    if b"<svg" in head:
        return False
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body", b"{", b"[")) or b"<html" in head


def prune_image_cache(app_root, cap: int = IMAGE_CACHE_CAP, target: int = IMAGE_CACHE_TARGET) -> dict:
    """The README image cache's size cap: when the folder holds more than
    `cap` bytes, the least recently used files (oldest mtime - load_images
    touches a file on every hit) are deleted until it's at or under `target`.
    cap=target=0 empties it (Settings' Clean up downloads). Best effort: a
    file that can't be read or deleted is logged and skipped. Returns
    {"total": bytes before, "removed": count, "freed": bytes, "failed": count}."""
    folder = Path(app_root) / ts.CACHE_DIR / IMAGE_CACHE_DIR
    res = {"total": 0, "removed": 0, "freed": 0, "failed": 0}
    files = []
    try:
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        files.append((st.st_mtime, st.st_size, entry.path))
                except OSError as err:
                    log(f"[browse] image cache: can't read {entry.name} ({err})")
    except FileNotFoundError:
        return res
    except OSError as err:
        log(f"[browse] image cache: can't list {folder} ({err})")
        return res
    total = res["total"] = sum(size for _, size, _ in files)
    if total <= cap:
        log(f"[browse] image cache: {len(files)} files, {format_size(total)} (cap {format_size(cap)}), nothing to prune")
        return res
    for _, size, path in sorted(files):  # oldest use first
        if total <= target:
            break
        try:
            os.remove(path)
        except OSError as err:
            res["failed"] += 1
            log(f"[browse] image cache: couldn't delete {Path(path).name} ({err})")
            continue
        total -= size
        res["removed"] += 1
        res["freed"] += size
    log(f"[browse] image cache pruned: {res['removed']} of {len(files)} files deleted, {format_size(res['freed'])} freed "
        f"({format_size(res['total'])} -> {format_size(total)}; cap {format_size(cap)}, target {format_size(target)}), "
        f"{res['failed']} failed")
    return res


_END = object()


def _parallel(items, work, workers: int) -> None:
    """work(item) for every item, `workers` at a time, taken in list order
    (the list is the priority); returns when all are done. Daemon threads,
    not concurrent.futures (whose workers the interpreter waits for at exit):
    closing VOLT mid-load never waits on a slow image host. An exception
    from one item is logged and the rest carry on."""
    items = list(items)
    if not items:
        return
    it, lock = iter(items), threading.Lock()

    def run() -> None:
        while True:
            with lock:
                item = next(it, _END)
            if item is _END:
                return
            try:
                work(item)
            except Exception as err:  # noqa: BLE001 - a worker never dies silently, the queue keeps draining
                log(f"[browse] background fetch of {clip(item)} failed: {err!r}")

    threads = [threading.Thread(target=run, name=f"browse-fetch-{i}", daemon=True) for i in range(min(workers, len(items)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def load_images(urls: list[str], app_version=None, *, app_root=None, max_bytes: int = IMAGE_MAX_BYTES, fetch=None,
                shrink=None, on_image=None, cancelled=None, workers: int = FETCH_WORKERS, budget_s: float = IMAGE_BUDGET_S,
                timeout: float = IMAGE_TIMEOUT_S, clock=time.monotonic) -> dict[str, bytes]:
    """url -> bytes for `urls` (image_urls' list; its order is the queue's),
    `workers` at a time: a badge host is skipped, the disk cache under
    `app_root` answers first (no network), else a fetch (`timeout` per
    socket operation) that is then cached. After `budget_s` from the start
    no new fetch begins - the queued ones are abandoned, one already in
    flight still lands. `cancelled()` true (a newer page, the window gone):
    everything still queued is dropped. `on_image(url, bytes)` runs on the
    worker as each one lands. A failure (network, HTTP, too big) is skipped
    and logged; its image stays blank; so is a web page / text reply
    (_is_text_body), never cached. `shrink(bytes) -> bytes | None` (the
    window's Qt shrink_image; None = no shrinking, the harness) runs on the
    worker before anything is cached or shown, so the first showing and
    every later cache hit are the same bytes: None back = it couldn't decode
    them (shown as is - most likely blank - and cached only under
    IMAGE_KEEP_RAW_MAX), a ValueError = too large to decode (skipped). A
    cache hit touches the file's mtime (prune_image_cache's "recently used")."""
    fetch = fetch or fetch_bytes
    start = clock()
    got: dict[str, bytes] = {}
    outcome: dict[str, str] = {}  # url -> cache / fetched / failed / badge / budget / cancelled (dict writes are atomic)

    def one(url: str) -> None:
        if cancelled is not None and cancelled():
            outcome[url] = "cancelled"
            return
        if is_badge(url):
            outcome[url] = "badge"
            return
        path = image_cache_path(app_root, url) if app_root else None
        data = None
        if path is not None:
            try:
                data = path.read_bytes()
                outcome[url] = "cache"
            except OSError:
                pass
            else:
                try:
                    os.utime(path)  # used now: the last to go when the cache is pruned
                except OSError:
                    pass
        if data is None:
            if clock() - start > budget_s:
                outcome[url] = "budget"
                return
            try:
                data = fetch(url, app_version, what="image", max_bytes=max_bytes, timeout=timeout)
                if _is_text_body(data):
                    raise ValueError(f"the reply is a web page or text, not an image ({len(data)} bytes)")
                cacheable = True
                if shrink is not None:
                    small = shrink(data)  # ValueError: too large to decode
                    if small is None:
                        cacheable = len(data) < IMAGE_KEEP_RAW_MAX
                        log(f"[browse] image {url}: couldn't be decoded ({len(data)} bytes) - "
                            f"{'cached as is' if cacheable else 'not cached'}")
                    else:
                        data = small
            except (ThunderstoreError, ValueError) as err:
                log(f"[browse] image {url}: skipped ({err})")
                outcome[url] = "failed"
                return
            outcome[url] = "fetched"
            if path is not None and cacheable:
                _cache_image(path, data)
        got[url] = data
        if on_image is not None:
            on_image(url, data)

    log(f"[browse] images: {len(urls)} queued, {min(workers, len(urls))} workers, budget {budget_s:g}s, "
        f"disk cache {'on' if app_root else 'off'}")
    _parallel(urls, one, workers)
    counts = Counter(outcome.values())
    log(f"[browse] images done in {clock() - start:.1f}s: {counts['cache']} from the cache, {counts['fetched']} fetched, "
        f"{counts['failed']} failed, {counts['badge']} badges skipped, {counts['budget']} skipped (over the {budget_s:g}s budget), "
        f"{counts['cancelled']} dropped (page left)")
    for why in ("badge", "budget"):
        skipped = [u for u in urls if outcome.get(u) == why]
        if skipped:
            log(f"[browse] images skipped ({why}): {clip(skipped, 600)}")
    return {u: got[u] for u in urls if u in got}


def fetch_bytes(url: str, app_version=None, *, what: str = "icon", max_bytes: int = ICON_MAX_BYTES,
                timeout: float | None = None) -> bytes:
    """A small binary (a card icon from ccdn.thunderstore.io, a README
    image). Only http(s) URLs; anything else is a ValueError. `timeout`:
    _get's (thunderstore.TIMEOUT_S unless given)."""
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"Not an http(s) URL: {url!r}")
    return _get(url, app_version, what, max_bytes=max_bytes, timeout=timeout)


def dependency_chain(dependencies: list[str], installed, framework: str | None, app_version=None, *,
                     fetch=None) -> dict:
    """What installing a package with these declared dependencies pulls in,
    given the open load order's installed full_names (`installed`) and its
    framework: {"satisfied": [full_names already there, framework included,
    declaration order], "missing": [full_names that get installed, each
    once, dependencies before dependents - install_mod's order], "problems":
    [(full_name, message)] for a dependency whose metadata couldn't be
    fetched or whose string isn't a package reference}. Missing
    dependencies are resolved recursively at Thunderstore's latest version
    (fetch = thunderstore.fetch_package), the same policy install_mod
    applies, stopping at CHAIN_LIMIT packages."""
    fetch = fetch or ts.fetch_package
    installed = set(installed)
    satisfied: list[str] = []
    missing: list[str] = []
    problems: list[tuple[str, str]] = []
    seen: set[str] = set()

    def visit(dep_strings) -> None:
        for dep in dep_strings:
            try:
                ref = ts.PackageRef.parse(dep)
            except ValueError as err:
                problems.append((str(dep), str(err)))
                continue
            full = ref.full_name
            if full in seen:
                continue
            seen.add(full)
            if full == framework or full in installed:
                satisfied.append(full)
                continue
            if len(missing) >= CHAIN_LIMIT:
                problems.append((full, CHAIN_LIMIT_MESSAGE))
                return
            try:
                meta = fetch(ref.namespace, ref.name, app_version)
            except ThunderstoreError as err:
                problems.append((full, str(err)))
                continue
            sub = meta.get("latest", {}).get("dependencies") or []
            visit([d for d in sub if isinstance(d, str)])
            missing.append(full)  # after its own dependencies: install order

    visit([d for d in dependencies if isinstance(d, str)])
    log(f"[browse] dependency chain: {len(satisfied)} satisfied, {len(missing)} to install {missing}, {len(problems)} problems")
    return {"satisfied": satisfied, "missing": missing, "problems": problems}


def parallel_dependency_chain(dependencies: list[str], installed, framework: str | None, app_version=None, *,
                              fetch=None, cache: dict | None = None, workers: int = FETCH_WORKERS) -> dict:
    """dependency_chain's exact answer (same order, same CHAIN_LIMIT cut-off,
    same problems), faster: the packages it will ask for are fetched first,
    level by level (breadth first), `workers` at a time, into `cache`
    (full_name -> fetch_package's dict; the window passes its own so a
    reopened page or Back costs nothing - successes only, a failure is
    retried next time), then dependency_chain runs over that cache. A
    package the warm-up didn't reach (past 2 x CHAIN_LIMIT) is fetched on
    demand as before."""
    fetch = fetch or ts.fetch_package
    cache = {} if cache is None else cache
    failed: dict[str, ThunderstoreError] = {}  # this run only
    installed = set(installed)
    seen: set[str] = set()
    hits = fetched = levels = 0
    start = time.monotonic()

    def new_refs(dep_strings) -> list:
        out = []
        for dep in dep_strings:
            if not isinstance(dep, str):
                continue
            try:
                ref = ts.PackageRef.parse(dep)
            except ValueError:
                continue  # dependency_chain reports it
            if ref.full_name in seen or ref.full_name == framework or ref.full_name in installed:
                continue
            seen.add(ref.full_name)
            out.append(ref)
        return out

    def warm(ref) -> None:
        try:
            cache[ref.full_name] = fetch(ref.namespace, ref.name, app_version)
        except ThunderstoreError as err:
            failed[ref.full_name] = err

    level = new_refs(dependencies)
    # ponytail: no cancel - a page left mid-warm-up still finishes its levels (at most 2 x CHAIN_LIMIT small
    # API calls, ~1-2 s; the results stay in the window's cache). Add a `cancelled` like load_images' if it shows.
    while level and fetched < 2 * CHAIN_LIMIT:
        level = level[:2 * CHAIN_LIMIT - fetched]
        todo = [r for r in level if r.full_name not in cache]
        hits += len(level) - len(todo)
        fetched += len(todo)
        levels += 1
        _parallel(todo, warm, workers)
        level = new_refs(d for r in level for d in ((cache.get(r.full_name) or {}).get("latest", {}).get("dependencies") or []))
    log(f"[browse] dependency chain warm-up: {fetched} fetched ({len(failed)} failed), {hits} from the window's cache, "
        f"{levels} levels, {time.monotonic() - start:.2f}s")

    def cached(namespace: str, name: str, app_version=None) -> dict:
        full = f"{namespace}-{name}"
        if full in cache:
            return cache[full]
        if full in failed:
            raise failed[full]
        log(f"[browse] dependency chain: {full} past the warm-up, fetched on demand")
        meta = fetch(namespace, name, app_version)
        cache[full] = meta
        return meta

    return dependency_chain(dependencies, installed, framework, app_version, fetch=cached)


def format_count(n) -> str:
    """4616657 -> "4,616,657"."""
    return f"{int(n):,}" if isinstance(n, int) and not isinstance(n, bool) else "-"


def format_size(n) -> str:
    """Bytes -> "3.1 MB" / "512 KB" / "12 B" (1024-based, one decimal from MB up)."""
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        return "-"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n // 1024} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.1f} GB"
