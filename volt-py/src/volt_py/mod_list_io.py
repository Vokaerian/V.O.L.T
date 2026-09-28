"""Mod list import/export formats (port of Electron's
src/electron/lib/modListIO.js, plus the export builders,
resolveWorkshopPlaceholders, reconcileLists' Active half (reconcile_active)
and the not-found Workshop-row helpers from src/renderer/src/lists.js).

Every importer returns an ordered, cleaned list of packageIds; the screen
applies it like loading a load order (RimWorldMainScreen._apply_import).
Export to RimPy .xml reuses mods_config.fresh_mods_config.

Pure Python, no Qt. The two rentry.co calls use stdlib urllib, like
community_rules.py; they're synchronous, the caller picks the thread.
"""

import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import net
from .applog import log
from .fsutil import read_text
from .ids import clean_ids
from .mods import workshop_id, workshop_urls
from .sort import mod_name
from .xml import get_ci, list_, parse_xml

# ponytail: urllib's timeout is per socket operation, not a total deadline like
# the JS's AbortSignal.timeout (same ceiling as community_rules.TIMEOUT_S).
RENTRY_TIMEOUT_S = 10
SAVE_HEAD_BYTES = 512 * 1024
NOT_A_LIST = "Doesn't look like a RimPy export or a RimSort mod list."
NO_SAVE_LIST = "This save has no recorded mod list."
PUBLISH_URL = "https://rentry.co/api/new"

# "Name [packageId][url]" at the end of a line (RimSort's clipboard format).
_RIMSORT_LINE = re.compile(r"\[([^\[\]]+)\]\[[^\[\]]*\]\s*$")
_PACKAGE_ID = re.compile(r"packageid:\s*([^\s(){}\[\]]+)", re.I)


# ---- parsers ----
def parse_rim_py_xml_text(text) -> list[str]:
    """RimPy export = a ModsConfig.xml. Anything around the <ModsConfigData>
    block (e.g. markdown fences on a rentry.co page) is ignored."""
    s = str(text)
    start = re.search(r"<ModsConfigData\b", s, re.I)
    end = -1
    for m in re.finditer(r"</ModsConfigData\s*>", s, re.I):
        end = m.end()  # last closing tag
    active_mods = None
    if start and end > start.start():
        try:
            root = parse_xml(s[start.start() : end])
        except ET.ParseError as err:
            # fast-xml-parser (the JS) is lenient; ElementTree isn't.
            raise ValueError(f"This isn't a RimPy mod list (not valid XML: {err}).") from err
        if root.tag.lower() == "modsconfigdata":
            active_mods = get_ci(root, "activeMods")
    if active_mods is None:
        raise ValueError("This isn't a RimPy mod list (no <ModsConfigData>/<activeMods> found).")
    return clean_ids(list_(active_mods))


def parse_rim_sort_text(text) -> list[str]:
    """RimSort clipboard export: "Name [packageId][url]" per line; header/blank lines skipped."""
    return clean_ids([m[1] for line in re.split(r"\r?\n", str(text)) if (m := _RIMSORT_LINE.search(line))])


def parse_rentry_markdown_text(text) -> list[str]:
    """rentry.co markdown (RimSort's page export, and ours: build_rentry_markdown).
    Every id follows "packageid:" whether in (...) or {...}; no markdown parsing needed."""
    return clean_ids(_PACKAGE_ID.findall(str(text)))


def detect_and_parse(text) -> list[str]:
    """Clipboard / rentry.co text: any of the three formats. Sniffs the first
    ~500 chars anywhere (not just a strict prefix), so XML inside a markdown
    code block works."""
    s = str(text)
    if re.search(r"<\?xml|<ModsConfigData", s[:500], re.I):
        ids = parse_rim_py_xml_text(s)
    elif re.search(r"packageid:", s, re.I):
        ids = parse_rentry_markdown_text(s)
    else:
        ids = parse_rim_sort_text(s)
    if not ids:
        raise ValueError(NOT_A_LIST)
    return ids


def read_save_mod_list(file_path) -> list[str]:
    """Mod ids from a RimWorld .rws save's <meta><modIds>. Only the meta block
    is parsed, never the (tens of MB) <game> tree.
    ponytail: assumes </meta> lies in the first 512KB (~53KB for a 600-mod
    save); past that it falls back to reading the whole file. Stream-scan for
    </meta> if that fallback ever matters."""
    with open(file_path, "rb") as f:
        text = f.read(SAVE_HEAD_BYTES).decode("utf-8", errors="replace")
    end = text.find("</meta>")
    if end < 0:
        text = read_text(file_path)
        end = text.find("</meta>")
    if end < 0:
        raise ValueError(NO_SAVE_LIST)
    try:
        root = parse_xml(text[: end + len("</meta>")] + "</savegame>")
    except ET.ParseError as err:
        raise ValueError(NO_SAVE_LIST) from err
    if root.tag.lower() != "savegame":
        raise ValueError(NO_SAVE_LIST)
    ids = clean_ids(list_(get_ci(get_ci(root, "meta"), "modIds")))
    if not ids:
        raise ValueError(NO_SAVE_LIST)
    return ids


# ---- rentry.co page: URL + HTML -> text ----
def rentry_page_url(value) -> str:
    """A rentry.co/rentry.org page URL (share link, /edit or old /raw link) -> the plain page URL."""
    s = str(value or "").strip()
    if not re.match(r"https?://", s, re.I):
        s = "https://" + s
    try:
        u = urllib.parse.urlsplit(s)
        u.port  # noqa: B018 - raises ValueError on a bad port, like `new URL` throwing
        host = u.hostname or ""
    except ValueError:
        raise ValueError(f"Not a valid URL: {value}") from None
    if not re.fullmatch(r"(www\.)?rentry\.(co|org)", host, re.I):
        raise ValueError(f"Not a rentry.co URL: {value}")
    p = re.sub(r"/+$", "", re.sub(r"/(edit|raw)$", "", re.sub(r"/+$", "", u.path), flags=re.I))
    if not p:
        raise ValueError(f"That URL has no rentry.co page in it: {value}")
    return f"https://{host}{p}"


_ENTITIES = {"lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ", "#39": "'", "#x27": "'"}


def sanitize_html(html) -> str:
    """Rendered HTML, stage 1: drop script/style blocks and comments (never visible text)."""
    s = re.sub(r"<(script|style)\b[\s\S]*?</\1\s*>", " ", str(html), flags=re.I)
    return re.sub(r"<!--[\s\S]*?-->", " ", s)


def strip_tags(html) -> str:
    """Stage 2: tags -> text. Block-ending tags become newlines (the RimSort
    text parser is line-based), other tags a space; &amp; decoded last.
    ponytail: regex tag strip, not an HTML parser; enough to find "packageid:" text."""
    s = re.sub(r"<br\b[^>]*>|</(p|li|div|h[1-6]|tr|pre|ol|ul)\s*>", "\n", str(html), flags=re.I)
    s = re.sub(r"<[^>]*>", " ", s)
    s = re.sub(r"&(lt|gt|quot|apos|nbsp|#39|#x27);", lambda m: _ENTITIES[m[1].lower()], s, flags=re.I)
    s = re.sub(r"&amp;", "&", s, flags=re.I)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n\s*", "\n", s)
    return s.strip()


def html_to_text(html) -> str:
    """Rendered HTML -> visible text."""
    return strip_tags(sanitize_html(html))


_WS_MARK = "\u0001"


def parse_rentry_page_html(html) -> list[str]:
    """A fetched rentry.co page -> ordered ids. A line with visible
    "packageid: x" (our exports, RimSort's warning boxes) gives x. A line whose
    only id is a Steam Workshop link's href (RimSort's Workshop entries: the
    packageid never renders) gives the sentinel "workshop:<id>", resolved
    against scanned mods by resolve_workshop_placeholders. Each link's id is
    swapped in as a marker *on its own line* before tags are stripped, so a
    line pairs only with its own link (a global href queue would desync on
    lines that carry both a link and a visible packageid). Nothing found ->
    generic detect_and_parse."""
    s = re.sub(r"<li\b", lambda m: "\n" + m[0], sanitize_html(html), flags=re.I)
    s = re.sub(r"<a\b[^>]*filedetails/\?id=([0-9]+)[^>]*>", rf" {_WS_MARK}\1{_WS_MARK} ", s, flags=re.I)
    text = strip_tags(s)
    ids = []
    for line in text.split("\n"):
        pid = _PACKAGE_ID.search(line)
        rs = _RIMSORT_LINE.search(line)  # a RimSort text line, url autolinked
        wid = re.search(rf"{_WS_MARK}([0-9]+){_WS_MARK}", line)
        if pid:
            ids.append(pid[1])
        elif rs:
            ids.append(rs[1])
        elif wid:
            ids.append(f"workshop:{wid[1]}")
    out = clean_ids(ids)
    return out if out else detect_and_parse(text.replace(_WS_MARK, ""))


def resolve_workshop_placeholders(ids: list[str], mods: dict, keep_unmatched: bool = False) -> dict:
    """lists.js resolveWorkshopPlaceholders: imported "workshop:<id>" sentinels
    (parse_rentry_page_html) -> the scanned Workshop mod with that folder id.
    Unmatched sentinels are dropped and counted ("skipped"), or with
    keep_unmatched (collection import) kept as-is and counted ("pending").
    {"ids": [...], "skipped": int, "pending": int}."""
    by_wid = {wid: m["id"] for m in mods.values() if (wid := workshop_id(m))}
    out, skipped, pending = [], 0, 0
    for i in ids:
        if not i.startswith("workshop:"):
            out.append(i)
        elif i[9:] in by_wid:
            out.append(by_wid[i[9:]])
        elif keep_unmatched:
            out.append(i)
            pending += 1
        else:
            skipped += 1
    return {"ids": out, "skipped": skipped, "pending": pending}


def reconcile_active(active, mods: dict) -> list[str]:
    """lists.js reconcileLists' Active half (App.jsx showLists: load, rescan,
    import, undo): every given id, trimmed / lowercased / deduped, in order -
    an id with no scanned mod stays (a "not found" row, so Save / Push never
    silently drop it), and a "workshop:<id>" sentinel whose Workshop item is
    scanned now (Subscribed, then Rescan) is swapped in place for that mod's
    id (resolve_workshop_placeholders with keep_unmatched, which is exactly
    reconcileLists' byWid step). The JS resolves first, then dedupes, so a
    sentinel resolving to an id already in the list is dropped as a
    duplicate: the first occurrence wins. Inactive (every scanned mod not in
    the result, by name) is the caller's, as it needs the scan order."""
    ids = resolve_workshop_placeholders(clean_ids(list(active or [])), mods, keep_unmatched=True)["ids"]
    return list(dict.fromkeys(ids))


# lists.js: /^(?:workshop:)?(\d+)$/ - JS \d is ASCII-only, and $ (no m flag)
# never matches before a trailing newline, hence re.ASCII + fullmatch.
_NOT_FOUND_WORKSHOP_ID = re.compile(r"(?:workshop:)?(\d+)", re.ASCII)


def not_found_workshop_id(mod_id: str | None, mods: dict) -> str | None:
    """lists.js notFoundWorkshopId: the Workshop id of a "not found" list
    entry (an id with no scanned mod) whose id itself is a Steam Workshop id -
    a bare numeric id (pre-1.1 ModsConfig.xml / RimPy lists name Workshop
    mods by folder id) or the "workshop:<id>" sentinel (rentry.co /
    collection import; resolve_workshop_placeholders keeps it with
    keep_unmatched). None otherwise. Such a row is "pending": the list
    renders it with Subscribe (screens/mod_list.py, RowDecor.pending)."""
    if not mod_id or mod_id in mods:
        return None
    m = _NOT_FOUND_WORKSHOP_ID.fullmatch(mod_id)
    return m[1] if m else None


def missing_workshop_rows(active: list[str], mods: dict) -> list[str]:
    """lists.js missingWorkshopRows (Settings > Steam > Check for missing
    Workshop mods): every Active-list id that's a not-found Workshop id, in
    list order."""
    return [i for i in active if not_found_workshop_id(i, mods)]


# ---- rentry.co network calls ----
def _request(req: urllib.request.Request) -> tuple[int, bytes]:
    """(HTTP status, body). A non-2xx answer is returned, not raised; not
    reaching the site at all raises OSError."""
    log(f"rentry: {req.get_method()} {req.full_url} (timeout {RENTRY_TIMEOUT_S}s)")
    try:
        with net.urlopen(req, timeout=RENTRY_TIMEOUT_S) as res:
            status, body = res.status, res.read()
    except urllib.error.HTTPError as err:
        status, body = err.code, b""
    except (OSError, http.client.HTTPException) as err:  # URLError, timeout, dropped connection
        log(f"rentry: {req.full_url} failed: {err!r}")
        raise OSError(f"Couldn't reach rentry.co: {getattr(err, 'reason', err)}.") from err
    log(f"rentry: HTTP {status}, {len(body)} bytes")
    return status, body


def fetch_rentry_page(url, app_version) -> str:
    """There is no unauthenticated raw-markdown route (/api/raw needs a
    rentry-auth header), so read the public rendered page; returns its raw
    HTML for parse_rentry_page_html."""
    page = rentry_page_url(url)
    req = urllib.request.Request(page, headers={"User-Agent": f"VOLT/{app_version or '?'} mod-list importer"})
    status, body = _request(req)
    if not 200 <= status < 300:
        raise OSError(f"rentry.co returned HTTP {status} for {page}.")
    return body.decode("utf-8-sig", errors="replace")  # like res.text()


def publish_rentry(text: str, app_version) -> str:
    """Anonymous, CSRF-exempt create endpoint (per github.com/radude/rentry).
    Form-encoded POST; JSON reply {status: '200', url} or {status, errors}. No
    edit_code/url sent. Returns the new page's URL."""
    req = urllib.request.Request(
        PUBLISH_URL,
        data=urllib.parse.urlencode({"text": text}).encode(),
        headers={
            "User-Agent": f"VOLT/{app_version or '?'} mod-list exporter",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    status, body = _request(req)
    if status == 429:
        raise OSError("rentry.co is rate-limiting requests (HTTP 429). Try again in a minute.")
    if not 200 <= status < 300:
        raise OSError(f"rentry.co returned HTTP {status} when publishing.")
    try:
        j = json.loads(body.decode("utf-8-sig"))
    except ValueError as err:  # the JS's res.json() just throws its parser error
        raise ValueError(f"rentry.co sent a reply that isn't JSON ({err}).") from err
    if not isinstance(j, dict):
        j = {}
    if str(j.get("status")) != "200" or not j.get("url"):
        errors = j.get("errors")
        if errors not in (None, "", 0, False):
            detail = errors if isinstance(errors, str) else json.dumps(errors, separators=(",", ":"))
        else:
            detail = str(j.get("content") or "")
        status_text = "undefined" if j.get("status") is None else j["status"]
        raise ValueError(f"rentry.co refused the upload (status {status_text})" + (f": {detail}" if detail else "."))
    u = str(j["url"])
    return u if re.match(r"https?://", u, re.I) else "https://rentry.co/" + u.lstrip("/")


# ---- export builders (lists.js) ----
def build_rim_sort_text(ids: list[str], mods: dict, app_version, game_version) -> str:
    """RimSort's clipboard format (also what rentry.co mod lists use): a
    header, then "Name [packageId][url]" per id; url is the Workshop page or
    "none". Not-found ids get a line too (name = id). Parsed back by
    parse_rim_sort_text."""
    return "\n".join([
        f"Created with VOLT v{app_version or '?'}",
        f"RimWorld game version this list was created for: {game_version or 'unknown'}",
        f"Total # of mods: {len(ids)}",
        "",
        *(f"{mod_name(mods, i)} [{i}][{(workshop_urls(mods.get(i)) or {}).get('web') or 'none'}]" for i in ids),
    ])


def build_rentry_markdown(ids: list[str], mods: dict, app_version, game_version) -> str:
    """rentry.co page markdown, mirroring RimSort's own "export to rentry.co"
    layout (header, !!! info/note admonitions, numbered list). Workshop mods
    are numbered links followed by visible "{packageid: id}" text (inside the
    link's parens rentry.co hides it, and import reads the rendered page);
    everything else (official/local/not-found) goes in a "!!! warning" box.
    Parsed back by parse_rentry_markdown_text / parse_rentry_page_html.
    ponytail: no preview images (we only have local files); needs the Steam API."""

    def line(n: int, i: str) -> str:
        name = mod_name(mods, i)
        url = (workshop_urls(mods.get(i)) or {}).get("web")
        return f"{n}. [{name}]({url}) {{packageid: {i}}}" if url else f"!!! warning {n}. {name} {{packageid: {i}}} "

    return "\n".join([
        "# RimWorld mod list",
        f"Created with VOLT v{app_version or '?'}",
        *([f"Mod list was created for game version: `{game_version}`"] if game_version else []),
        "!!! info Mods without a Steam Workshop link are shown in a highlighted box with their packageid.",
        "",
        f"!!! note Mod list length: `{len(ids)}`",
        "",
        *(line(n, i) for n, i in enumerate(ids, 1)),
    ])
