"""Steam's keyless Web API (port of Electron's src/electron/lib/steamWebApi.js):
the ISteamRemoteStorage endpoints that need no personal API key. Distinct
from the SteamCMD download engine (steam_cmd.py) and from the Steamworks
client SDK (subscribe through the running Steam client; not in this port
yet), and from Workshop search (needs a key; deferred).

Used by the "From Steam Workshop..." import (screens/collection_dialog.py):
resolve_collection turns a pasted collection URL / id into the collection's
ordered items - or, when the id is a single mod's, a one-item "collection".
Update tracking will reuse get_published_file_details (time_updated,
subscriber counts), so normalize_details keeps every generally useful field,
not just the title.

Pure Python, no Qt; urllib through the `env` seam (steam_cmd.py's pattern) so
a check harness (tools/checks/volt_py_steam_web_api.py) can fake Steam's
replies. Same known limitation as every other direct fetch in the app: no
system/PAC proxy. A failed request is a SteamWebApiError with a readable,
user-facing message (the JS's texts, verbatim); a bad argument (not a Workshop
id / URL) is a ValueError with the same kind of message. Nothing here logs
less than the JS did - more (CLAUDE.md section 10): every request, its
outcome and every skipped nested collection lands in volt.log.
"""

import http.client
import json
import math
import re
import types
import urllib.error
import urllib.parse
import urllib.request

from . import net
from .applog import clip, log

API = "https://api.steampowered.com/ISteamRemoteStorage"
TIMEOUT_S = 10.0
# Ids per GetPublishedFileDetails request. Valve documents no hard cap; 100
# keeps each request small.
DETAILS_CHUNK = 100
# Collections can list other collections; they're expanded in place, this deep at most.
MAX_COLLECTION_DEPTH = 3
RIMWORLD_APP_ID = 294100
RESULT_OK = 1  # Steam EResult k_EResultOK
FILETYPE_COLLECTION = 2  # EWorkshopFileType k_EWorkshopFileTypeCollection
# JS /^\d{1,20}$/: \d is ASCII-only there, and $ never matches before a
# trailing newline without the m flag - hence re.ASCII + fullmatch.
_WS_ID = re.compile(r"\d{1,20}", re.ASCII)
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_HOST = re.compile(r"^(www\.)?steamcommunity\.com$", re.I)
_PATH = re.compile(r"^/(sharedfiles|workshop)/filedetails/?$", re.I)
# WHATWG URL (what `new URL()` implements), the parts a pasted link can hit:
# tabs / newlines are dropped anywhere; after a special scheme any run of / or
# \ is the authority start; \ is / up to the query; a host with one of these
# code points in it is an invalid URL (not a host that merely fails the
# steamcommunity check); a host whose last label is a number is an IPv4
# address and fails as a whole when it isn't a valid one (so 21 digits are
# "not a URL", not "not steamcommunity.com").
_BAD_HOST_CHAR = re.compile(r"[\s#%/:<>?@\[\\\]^|]")
_BAD_OPAQUE_HOST_CHAR = re.compile(r"[\s#/:<>?@\[\\\]^|]")  # a non-special scheme's host: % allowed, may be empty
_SPECIAL_SCHEMES = {"http", "https", "ws", "wss", "ftp", "file"}
_IPV4_DIGITS = {10: "0123456789", 16: "0123456789abcdefABCDEF", 8: "01234567"}

# Check-harness seam (no network in the sandbox).
env = types.SimpleNamespace(urlopen=net.urlopen)


class SteamWebApiError(RuntimeError):
    """Steam's Web API couldn't be reached, or couldn't/wouldn't return what
    was asked for. The message is what the user sees."""


def _ipv4_number(part: str):
    """WHATWG IPv4 number parser: the value, or None when `part` isn't one."""
    if part == "":
        return None
    radix = 10
    if len(part) >= 2 and part[:2].lower() == "0x":
        part, radix = part[2:], 16
    elif len(part) >= 2 and part[0] == "0":
        part, radix = part[1:], 8
    if part == "":
        return 0
    if any(ch not in _IPV4_DIGITS[radix] for ch in part):
        return None
    return int(part, radix)


def _invalid_ipv4_host(host: str) -> bool:
    """WHATWG host parser: a host that "ends in a number" is parsed as IPv4;
    True when that parse fails (the whole URL is then invalid). A host that
    doesn't end in a number is a domain, never invalid here."""
    parts = host.split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    last = parts[-1]
    if not (last.isascii() and last.isdigit()) and not re.fullmatch(r"0[xX][0-9a-fA-F]*", last):
        return False
    if len(parts) > 4:
        return True
    numbers = [_ipv4_number(p) for p in parts]
    if any(n is None for n in numbers) or any(n > 255 for n in numbers[:-1]):
        return True
    return numbers[-1] >= 256 ** (5 - len(numbers))


def _parse_url(s: str) -> tuple[str, str, str]:
    """(host, path, query) of `s` the way `new URL()` sees them, with the
    WHATWG normalizations above and the authority checked by hand (urllib's
    urlsplit validates brackets anywhere in the authority, and refuses the
    empty port `host:/` that `new URL()` allows); ValueError where `new URL()`
    would throw. Not ported: IDNA/UTS46 processing of a non-ASCII host - such
    a host is taken as it is (lowercased), so a junk non-ASCII host that
    Chromium rejects (a Bidi-rule failure) is refused here one step later, as
    "not steamcommunity.com" instead of "not a URL"; a real IDN can't be
    steamcommunity.com anyway. Nor the path's percent-encoding."""
    if not _SCHEME.match(s):  # the JS tests the scheme before the URL parser drops tabs / newlines
        s = "https://" + s
    s = re.sub(r"[\t\n\r]", "", s)
    scheme, _, after = s.partition("://")
    special = scheme.lower() in _SPECIAL_SCHEMES
    if special:  # any run of / and \ opens the authority; \ is / up to the query
        after = after.lstrip("/\\")
        cut = re.search(r"[?#]", after)
        head, rest = (after[:cut.start()], after[cut.start():]) if cut else (after, "")
        after = head.replace("\\", "/") + rest
    authority = re.split(r"[/?#]", after, maxsplit=1)[0]
    rest = after[len(authority):]
    path, _, query = rest.partition("?")
    path, query = path.split("#", 1)[0], query.split("#", 1)[0]
    if special:  # dot segments: /a/../sharedfiles/filedetails/ is /sharedfiles/filedetails/
        out: list[str] = []
        segments = path.split("/")[1:] if path else []
        for i, seg in enumerate(segments):
            if seg == "..":
                if out:
                    out.pop()
                if i == len(segments) - 1:
                    out.append("")
            elif seg == ".":
                if i == len(segments) - 1:
                    out.append("")
            else:
                out.append(seg)
        path = "/" + "/".join(out)
    credentials, at, host_port = authority.rpartition("@")
    if host_port.startswith("["):  # an IPv6 literal: taken as a host, its syntax not checked
        end = host_port.find("]")
        if end < 0 or (host_port[end + 1:] and not host_port[end + 1:].startswith(":")):
            raise ValueError("bad IPv6 host")
        host, port = host_port[:end + 1], host_port[end + 2:]
    else:
        host, colon, port = host_port.rpartition(":") if ":" in host_port else (host_port, "", "")
        if not host and (colon or at):  # `:80` or `user@` with no host: host-missing, whatever the scheme
            raise ValueError("missing host")
        if special:
            # WHATWG: the host is percent-decoded first, then checked; a % left over (%25) is forbidden
            host = urllib.parse.unquote(host, errors="replace").lower()
            if not host or _BAD_HOST_CHAR.search(host) or _invalid_ipv4_host(host):
                raise ValueError("invalid host")
        elif _BAD_OPAQUE_HOST_CHAR.search(host):  # an opaque host: kept as it is, may be empty
            raise ValueError("invalid host")
    if port and (not (port.isascii() and port.isdigit()) or int(port) > 65535):
        raise ValueError("bad port")
    return host, path, query


def collection_id_from(value) -> str:
    """A pasted collection (or single mod, resolve_single_item): a bare
    Workshop id, or a steamcommunity.com .../sharedfiles/filedetails/?id=N or
    .../workshop/filedetails/?id=N page URL (scheme optional, extra query
    params fine). Same normalize-then-check shape as mod_list_io's
    rentry_page_url. ValueError otherwise."""
    s = str(value if value is not None else "").strip()
    if _WS_ID.fullmatch(s):
        return s
    try:
        host, path, query = _parse_url(s)
    except ValueError:
        raise ValueError(f"Not a Steam Workshop URL or id: {value}") from None
    if not _HOST.match(host):
        raise ValueError(f"Not a steamcommunity.com URL: {value}")
    if not _PATH.match(path):
        raise ValueError(f"That URL isn't a Steam Workshop page (.../filedetails/?id=...): {value}")
    ids = urllib.parse.parse_qs(query, keep_blank_values=True).get("id") or [""]
    wid = ids[0].strip()  # URLSearchParams.get: the first `id`
    if not _WS_ID.fullmatch(wid):
        raise ValueError(f"That URL has no Workshop id in it: {value}")
    return wid


def to_id(value) -> str:
    s = str(value if value is not None else "").strip()
    if not _WS_ID.fullmatch(s):
        raise ValueError(f"Not a Steam Workshop id: {value}")
    return s


def num(value):
    """The JS `num`: None for a missing / empty / non-numeric value, else the
    number (an int when it is one - Steam sends file_size as a string,
    result as an int, banned as a bool)."""
    if value is None or value == "" or isinstance(value, (dict, list)):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        n = value
    else:
        try:
            n = float(str(value).strip())
        except ValueError:
            return None
    if not math.isfinite(n):
        return None
    return int(n) if n.is_integer() else n


def post(method: str, fields: dict, app_version=None) -> dict:
    """POST a form-encoded request; returns the reply's `response` object."""
    url = f"{API}/{method}/v1/"
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={
            "User-Agent": f"VOLT/{app_version or '?'} Steam Workshop lookup",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    log(f"[steamWebApi] POST {method} ({len(fields)} fields, timeout {TIMEOUT_S:g}s)")
    try:
        with env.urlopen(req, timeout=TIMEOUT_S) as res:
            status, body = getattr(res, "status", 200), res.read()
    except urllib.error.HTTPError as err:  # fetch() resolves these; urllib raises them
        log(f"[steamWebApi] {method}: HTTP {err.code}")
        raise SteamWebApiError(f"Steam's Web API returned HTTP {err.code} ({method}).") from err
    except (OSError, http.client.HTTPException) as err:  # URLError, timeout, dropped connection
        log(f"[steamWebApi] {method}: request failed: {err!r}")
        reason = getattr(err, "reason", None) or str(err) or repr(err)
        raise SteamWebApiError(
            f"Couldn't reach Steam's Web API ({reason}). Check your internet connection."
        ) from err
    log(f"[steamWebApi] {method}: HTTP {status}, {len(body)} bytes")
    if not 200 <= status < 300:
        raise SteamWebApiError(f"Steam's Web API returned HTTP {status} ({method}).")
    try:
        j = json.loads(body.decode("utf-8-sig", errors="replace"))
    except ValueError as err:
        log(f"[steamWebApi] {method}: reply isn't JSON: {err} - {clip(body[:200])}")
        raise SteamWebApiError(f"Steam's Web API sent a reply VOLT couldn't read ({method}).") from err
    response = j.get("response") if isinstance(j, dict) else None
    # JS: typeof j.response === 'object' && j.response - an array passes too, and
    # then behaves like an object with no fields.
    if not isinstance(response, (dict, list)):
        log(f"[steamWebApi] {method}: reply has no response object: {clip(j)}")
        raise SteamWebApiError(f"Steam's Web API sent an unexpected reply ({method}).")
    return response if isinstance(response, dict) else {}


def get_collection_details(collection_id, app_version=None) -> dict:
    """One collection -> {"id", "children": [{"id", "sort_order", "file_type"}]}
    in the collection's own order (sortorder). Raises if Steam can't return
    it (private, friends-only, deleted) or it has no children (not a
    collection, or empty)."""
    cid = to_id(collection_id)
    r = post("GetCollectionDetails", {"collectioncount": "1", "publishedfileids[0]": cid}, app_version)
    details = r.get("collectiondetails")
    d = next(
        (x for x in (details if isinstance(details, list) else []) if isinstance(x, dict) and str(x.get("publishedfileid")) == cid),
        None,
    )
    if d is None or num(d.get("result")) != RESULT_OK:
        result = d.get("result", "missing") if d is not None else "missing"
        log(f"[steamWebApi] collection {cid}: not returned (result {result})")
        raise SteamWebApiError(
            f"Steam couldn't return collection {cid} (result {result}): it may be private, friends-only or deleted."
        )
    kids = d.get("children")
    kids = kids if isinstance(kids, list) else []
    if not kids:
        log(f"[steamWebApi] collection {cid}: no children")
        raise SteamWebApiError(f"Workshop item {cid} isn't a collection, or the collection is empty.")
    children = []
    for i, c in enumerate(kids):
        c = c if isinstance(c, dict) else {}
        child_id = str(c.get("publishedfileid"))
        if not _WS_ID.fullmatch(child_id):
            continue
        sort_order = num(c.get("sortorder"))
        file_type = num(c.get("filetype"))
        children.append({
            "id": child_id,
            "sort_order": sort_order if sort_order is not None else i,
            "file_type": file_type if file_type is not None else 0,
            "_i": i,
        })
    children.sort(key=lambda c: (c["sort_order"], c["_i"]))
    for c in children:
        del c["_i"]
    log(f"[steamWebApi] collection {cid}: {len(children)} children "
        f"({sum(1 for c in children if c['file_type'] == FILETYPE_COLLECTION)} nested collections)")
    return {"id": cid, "children": children}


def normalize_details(wid: str, d) -> dict:
    """Steam's per-item detail record -> a plain dict. found=False (only id
    and result set) for an item Steam won't return: removed, private or
    banned."""
    if not isinstance(d, dict) or num(d.get("result")) != RESULT_OK:
        return {"id": wid, "found": False, "result": num(d.get("result")) if isinstance(d, dict) else None}
    tags = d.get("tags")
    return {
        "id": wid,
        "found": True,
        "result": RESULT_OK,
        "title": d["title"] if isinstance(d.get("title"), str) else None,
        "app_id": num(d.get("consumer_app_id")),
        "creator": str(d["creator"]) if d.get("creator") is not None else None,
        "file_size": num(d.get("file_size")),
        "preview_url": d["preview_url"] if isinstance(d.get("preview_url"), str) and d["preview_url"] else None,
        "time_created": num(d.get("time_created")),
        "time_updated": num(d.get("time_updated")),
        "visibility": num(d.get("visibility")),
        "banned": bool(num(d.get("banned"))),
        "subscriptions": num(d.get("subscriptions")),
        "lifetime_subscriptions": num(d.get("lifetime_subscriptions")),
        "favorited": num(d.get("favorited")),
        "lifetime_favorited": num(d.get("lifetime_favorited")),
        "views": num(d.get("views")),
        "tags": [
            t for t in ((x.get("tag") if isinstance(x, dict) else x) for x in (tags if isinstance(tags, list) else []))
            if isinstance(t, str)
        ],
    }


def get_published_file_details(ids, app_version=None) -> list[dict]:
    """Workshop ids -> their details (normalize_details), one entry per
    distinct id, in input order. Chunked (DETAILS_CHUNK per request),
    sequentially."""
    wanted = list(dict.fromkeys(to_id(i) for i in (ids if isinstance(ids, (list, tuple)) else [ids])))
    by_id: dict[str, dict] = {}
    for start in range(0, len(wanted), DETAILS_CHUNK):
        chunk = wanted[start:start + DETAILS_CHUNK]
        fields = {"itemcount": str(len(chunk))}
        for i, wid in enumerate(chunk):
            fields[f"publishedfileids[{i}]"] = wid
        r = post("GetPublishedFileDetails", fields, app_version)
        details = r.get("publishedfiledetails")
        for d in (details if isinstance(details, list) else []):
            if isinstance(d, dict) and d.get("publishedfileid") is not None:
                by_id[str(d["publishedfileid"])] = d
    out = [normalize_details(wid, by_id.get(wid)) for wid in wanted]
    log(f"[steamWebApi] details for {len(wanted)} item(s): {sum(1 for d in out if d['found'])} found")
    return out


def resolve_single_item(wid: str, app_version=None) -> dict | None:
    """A single Workshop item as a "collection of one" (resolve_collection's
    reply shape, plus single=True), or None when Steam doesn't return it as
    an item. A collection page and a single mod's page share one URL shape
    (filedetails/?id=N), so only Steam's reply tells them apart:
    resolve_collection tries this when the collection lookup fails.
    ponytail: an empty collection is told apart from a mod by file_size 0
    (mods always have a file); use a file_type field if Steam's reply ever
    needs it."""
    (d,) = get_published_file_details([wid], app_version)
    if not d["found"] or d["file_size"] == 0:
        log(f"[steamWebApi] item {wid}: {'not returned' if not d['found'] else 'file_size 0'}, not a single mod")
        return None
    if d["app_id"] is not None and d["app_id"] != RIMWORLD_APP_ID:
        raise SteamWebApiError(f"Workshop item {wid} isn't a RimWorld mod (it belongs to Steam app {d['app_id']}).")
    log(f"[steamWebApi] item {wid}: a single mod, {d['title']!r}")
    return {
        "collection_id": wid,
        "single": True,
        "title": d["title"],
        "nested_collections": 0,
        "skipped_collections": 0,
        "details_error": None,
        "items": [{"position": 1, "id": wid, "title": d["title"], "details": d}],
    }


def resolve_collection(value, app_version=None) -> dict:
    """Collection import: a pasted URL / id -> the collection's items, in
    order: {"collection_id", "single": False, "title", "nested_collections",
    "skipped_collections", "details_error", "items": [{"position", "id",
    "title", "details"}]}. A single mod's URL / id comes back as a one-item
    collection (resolve_single_item, single=True). Nested collections are
    expanded in place (once each, MAX_COLLECTION_DEPTH deep); a duplicate
    item keeps its first position. Titles come from one details lookup; if
    that fails the ids still come back (title None, details_error set) -
    names are a nicety, the ordered ids are the import. Matching items
    against installed mods is the caller's (mod_list_io
    resolve_workshop_placeholders), which holds the scan."""
    collection_id = collection_id_from(value)
    log(f"[steamWebApi] resolving {value!r} -> Workshop id {collection_id}")
    ids: list[str] = []
    seen: set[str] = set()
    visited: set[str] = set()
    counts = {"nested": 0, "skipped": 0}

    def expand(cid: str, depth: int) -> None:
        visited.add(cid)
        children = get_collection_details(cid, app_version)["children"]
        for c in children:
            if c["file_type"] == FILETYPE_COLLECTION:
                if c["id"] in visited:
                    continue
                if depth >= MAX_COLLECTION_DEPTH:
                    log(f"[steamWebApi] nested collection {c['id']} skipped: deeper than {MAX_COLLECTION_DEPTH}")
                    counts["skipped"] += 1
                    continue
                try:
                    expand(c["id"], depth + 1)
                    counts["nested"] += 1
                except SteamWebApiError as err:
                    log(f"[steamWebApi] nested collection {c['id']} skipped: {err}")
                    counts["skipped"] += 1
            elif c["id"] not in seen:
                seen.add(c["id"])
                ids.append(c["id"])

    try:
        expand(collection_id, 1)
    except SteamWebApiError as err:
        # Not a (readable, non-empty) collection: maybe a single mod. If that
        # lookup fails too, the collection error is the one reported.
        single = None
        try:
            single = resolve_single_item(collection_id, app_version)
        except SteamWebApiError as e:
            if "isn't a RimWorld mod" in str(e):
                raise
            log(f"[steamWebApi] single-item fallback for {collection_id} failed too: {e}")
        if single:
            return single
        raise err
    if not ids:
        raise SteamWebApiError(f"Collection {collection_id} has no Workshop items in it.")

    details: dict[str, dict] | None = None
    details_error = None
    try:
        details = {d["id"]: d for d in get_published_file_details([collection_id, *ids], app_version)}
    except SteamWebApiError as err:
        log(f"[steamWebApi] item details unavailable: {err}")
        details_error = str(err)
    own = details.get(collection_id) if details else None
    if own and own["found"] and own["app_id"] is not None and own["app_id"] != RIMWORLD_APP_ID:
        raise SteamWebApiError(
            f"Collection {collection_id} isn't a RimWorld collection (it belongs to Steam app {own['app_id']})."
        )
    title = own["title"] if own and own["found"] else None
    log(f"[steamWebApi] collection {collection_id} {title!r}: {len(ids)} items, {counts['nested']} nested "
        f"collections expanded, {counts['skipped']} skipped, details {'ok' if details else 'unavailable'}")
    items = []
    for i, wid in enumerate(ids):
        d = details.get(wid) if details else None
        items.append({"position": i + 1, "id": wid, "title": d["title"] if d and d["found"] else None, "details": d})
    return {
        "collection_id": collection_id,
        "single": False,
        "title": title,
        "nested_collections": counts["nested"],
        "skipped_collections": counts["skipped"],
        "details_error": details_error,
        "items": items,
    }
