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
README / changelog images: markdown_image_urls picks the http(s) image
links out of the markdown and prefetch_images fetches them (a size cap
each, failures skipped) on the job thread, so the window can hand them to
its text browser before the markdown is set - no browser-side network.

Also here: PagedListing - the browser's own pages over that stream, every
one PAGE_SIZE long with the pinned packages taken out (the site's page 1
holds them, so its pages and VOLT's pages drift by that many; the class
tops a page up from the next site page and keeps the offsets consistent);
dependency_chain (which of a package's dependencies the open load
order already has, which get pulled in - recursively, at Thunderstore's
latest, THUNDERSTORE.md §1 / §9's policy - so the detail view's Install
button can say "+ N dependencies"), fetch_bytes for the card icons (ccdn.
thunderstore.io), and the number formatting the cards use.

Pure Python, no Qt; every request goes through thunderstore.env.urlopen (the
harness seam) with the same User-Agent. tools/checks/volt_py_thunderstore_
browse.py fakes the site.
"""

import http.client
import json
import re
import threading
import urllib.error
import urllib.parse
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


def team_page_url(community: str, namespace: str) -> str:
    """The author's page on the site (the header's author link)."""
    return f"{ts.SITE}/c/{community}/p/{namespace}/"


def dependants_page_url(community: str, namespace: str, name: str) -> str:
    """The site's "other mods that depend on this" page (the right column's Dependants link)."""
    return f"{ts.SITE}/c/{community}/p/{namespace}/{name}/dependants/"


def _get(url: str, app_version, what: str, *, max_bytes: int | None = None) -> bytes:
    """One GET through the env seam; HTTP / network failures are
    ThunderstoreErrors with user-facing text (`what` names the thing)."""
    log(f"[browse] GET {url}")
    try:
        with ts.env.urlopen(ts._request(url, app_version), timeout=ts.TIMEOUT_S) as res:
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


def markdown_image_urls(markdown: str) -> list[str]:
    """The http(s) image URLs a markdown text references, in order, each once."""
    out: list[str] = []
    for m in _MD_IMAGE.finditer(markdown or ""):
        url = m.group(1) or m.group(2) or ""
        if url.startswith(("http://", "https://")) and url not in out:
            out.append(url)
    return out


def prefetch_images(markdown: str, app_version=None, *, limit: int = IMAGE_LIMIT,
                    max_bytes: int = IMAGE_MAX_BYTES, fetch=None) -> dict[str, bytes]:
    """url -> bytes for the first `limit` images of `markdown`; one that
    fails (network, HTTP, too big) is skipped and logged - the text still
    shows, that image stays blank. Meant for the job thread."""
    fetch = fetch or fetch_bytes
    out: dict[str, bytes] = {}
    urls = markdown_image_urls(markdown)
    for url in urls[:limit]:
        try:
            out[url] = fetch(url, app_version, what="image", max_bytes=max_bytes)
        except (ThunderstoreError, ValueError) as err:
            log(f"[browse] image {url}: skipped ({err})")
    if len(urls) > limit:
        log(f"[browse] {len(urls) - limit} more images not fetched (limit {limit})")
    return out


def fetch_bytes(url: str, app_version=None, *, what: str = "icon", max_bytes: int = ICON_MAX_BYTES) -> bytes:
    """A small binary (a card icon from ccdn.thunderstore.io). Only http(s)
    URLs; anything else is a ValueError."""
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"Not an http(s) URL: {url!r}")
    return _get(url, app_version, what, max_bytes=max_bytes)


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
                problems.append((full, f"more than {CHAIN_LIMIT} dependencies; the rest aren't listed here"))
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
