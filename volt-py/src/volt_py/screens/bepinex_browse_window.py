"""Browse Mods window (THUNDERSTORE.md §5; Valheim stage 3f): the in-app
Thunderstore browser, built against the signed-off design
https://claude.ai/artifact/KeNe4nnwPVmCgfxrpbXBCZ - the BrowseMods
artboard (as amended 2026-09-29) and the PackageDetail artboard reworked
and signed off 2026-09-29 as a Thunderstore-style page - in the app's
large-modal shape (QDialog, 16px padding, the ValidationWindow /
ScanIssuesWindow / Edit Config convention). Game-agnostic: it takes the
game's ThunderstoreGame (the community slug) and callables from the
manager screen, nothing else.

Two pages in one window (a QStackedWidget, a short fade between them):

  Browse   Browse Thunderstore Mods    [Show deprecated] [Show NSFW] [✕]
           [Search mods...             ] [Category: All v] [Sort: v]
           4-column card grid (icon, name, "by author", description,
           "⬇ downloads", Install), the cards sharing the grid's whole
           width; 16 per page = 4 rows, every page full (the pinned
           packages the site puts first are taken out and the page topped
           up from the next site page - PagedListing), the grid scrolls
                      ‹ Prev   Page 1 of 337   Next ›
  Detail   [← Back to results]                                         [✕]
           [This package has been deprecated and may no longer be ...]
             (full width, --warn banner; only for a deprecated package)
           ┌ header card ─────────────────────────────┐ ┌ right column ─┐
           │ icon │ Name (22px)         [Version: v]  │ │ [Install X + N │
           │      │ short description                │ │  deps to <lo>] │
           │      │ 👥 author (site)  🔗 website      │ │ [Team-Pkg-ver ⧉]│
           │      │ ⬇ downloads · ★ ratings · size   │ │ Latest version │
           └──────────────────────────────────────────┘ │ Last updated  │
           [Details] [Required (N)] [Versions] [Changelog]│ First uploaded│
           ┌ tab body ────────────────────────────────┐ │ Downloads     │
           │ Details: the README (images included),   │ │ Likes / Size  │
           │   the required-mods summary under it     │ │ Dependants ↗  │
           │ Required: one rich row per dependency,   │ │ Categories    │
           │   a click opens that package's page      │ │               │
           │ Versions: version · date · downloads ·   │ │  [chip] [chip]│
           │   [Install x.y.z] / Installed on the     │ └───────────────┘
           │   version this load order has            │
           │ Changelog: the version's changelog       │
           │ Wiki (N): a page rail (the Help window's)│
           │   beside the selected page in a well     │
           └──────────────────────────────────────────┘
           The right column always shows the LATEST version; the header's
           version selector drives the Install button, Required and
           Changelog (and Details' README / dependency block). A category
           chip returns to the results filtered by it; the author name
           opens the team's page on the site, Dependants the site's
           dependants page. Loading and error states (with Retry) take
           the tab body's place. Versions: the row of the version the open
           load order has reads Installed; any other row's Install switches
           the mod to that version in place (the screen's `switch_version`
           = update_mod with a pinned version - newer or older); the big
           button offers "Update <Name> to <latest>" when an older version
           is installed and "already in" only at the latest.

READMEs: split_html_blocks (thunderstore_browse) separates raw-HTML chunks
(a whole README written as <div>/<h1>/<img> HTML, as OdinArchitect's is)
from markdown; the markdown parts go through Qt's markdown importer into
HTML, the HTML parts pass through, and the join is set as one HTML
document - Qt's importer on its own loses everything after an unclosed
<div> or a bare <img>. Images arrive after the text (0.6.31, below) and are
served through loadResource scaled to the README box's width (never
upscaled, tall ones capped); the document is set again (scroll kept) REFIT_MS
after the last arrival or resize. One not there (yet, or ever) is a blank box.

Show deprecated / Show NSFW (checkable buttons, the Edit Config Filter
toggle's look): both off on every open (session-only, never saved); either
one flipped reloads the listing from page 1 with the site's deprecated= /
nsfw= set to include those packages alongside the rest. A deprecated
card carries a red "Deprecated" pill before its name.

Data (volt_py/thunderstore_browse.py): every search / sort / category change
and page turn is one or two small requests to the site's own paged listing
(Option B; a PagedListing per search keeps the site pages it fetched) -
nothing is fetched until it's asked for, and only what this window already
showed is kept (in memory, dying with the window). Sort opens on Most
downloaded (user, 2026-09-29). Search waits SEARCH_DEBOUNCE_MS after the
last keystroke; a reply for a query that was superseded meanwhile is dropped
(a generation counter). Pinned packages (the framework pack, r2modman) never
appear. Icons load lazily on a small worker pool (_IconLoader, newest
request first, the current page's queue replacing the last page's) behind
the mockup's blank placeholder. A detail page is one job: the listing
detail, the versions list, the wiki index, the selected version's metadata,
README + changelog text - then the page shows (header, facts, version
picker, the README's text) and two background steps start (0.6.31; they used
to be inside the job, a modpack's page sat on "Loading..." for minutes): the
images (the README's, then the changelog's, thunderstore_browse.load_images
- FETCH_WORKERS at once, the disk cache <APP-ROOT>/cache/readme-images/
first, badge hosts skipped, an IMAGE_BUDGET_S budget per page; a fetched one
shrunk by shrink_image - at most IMAGE_MAX_WIDTH wide, re-encoded - before
it is cached or shown; the cache held under 100 MB by a prune when the
window opens; each merged into its _Readme as it lands through _ImageFeed,
no network inside the widget) and the dependency chain
(parallel_dependency_chain over the window's own package cache,
`_pkg_cache`, so reopening a page or Back refetches nothing). Until the
chain lands the big Install button shows its plain label but is disabled,
the dependency sub-line says it is checking and the Required pills read
Checking.... Picking another version is the same job minus the package-level
pieces, then the same two steps for that version. Every late arrival for a
page, version or wiki page no longer showing (`_detail_gen` / `_wiki_gen`),
or after the window closed, is dropped, and its queued image fetches are
abandoned.

Wiki (TODO #12, built 2026-09-30, direct implementation): the whole-page job
also fetches the package's wiki index (thunderstore_browse.fetch_wiki_
index; a 404 = no wiki, any failure logged and treated the same) - the tab
shows only when there are pages, labelled "Wiki (N)", the rail in
order_wiki_pages' order. Pages load lazily: nothing until the tab is first
opened (then its first page), one job per page picked (its markdown; its
images then load in the background like the README's), kept per package in
`_wiki_pages` (reset when another package opens; a version pick never
touches the wiki - it's package-level); a superseded page reply is dropped
(`_wiki_gen`). Loading / error + Retry show inside the page pane.

Links in a README / changelog / wiki page (_Readme._open_link): absolute
ones open in the system browser (as setOpenExternalLinks did), "#section"
scrolls, anything relative (a repo file, another wiki page) is ignored and
logged - Qt's own handling would navigate the box to a blank page.

Install (a card's button, the right column's big one, or a Versions row)
hands the PackageRef to the manager screen's install callback - the same
job as "Add mod..." (download into the shared cache if absent,
dependencies first, appended to the open load order's Active list, the
screen's lists refreshed) - and the window stays open so the next mod can
follow; the button reads Installing... then Installed. The dependency
block and the Install label come from thunderstore_browse.dependency_chain
(run as parallel_dependency_chain) over the selected version's declared
dependencies against what the load order already has. The Details tab's
block (0.6.31) is one summary line - "41 required mods: 0 already
installed, 41 will be installed." and a "See the Required tab" link - plus
only the dependencies with a problem (at most DEPS_PROBLEMS_SHOWN, then "and
N more"); the README's well keeps README_MIN_HEIGHT whatever sits below it,
so a modpack's page no longer grows the window or squeezes the README.

Download bars (0.6.26, PLAN.md §11 (c)): the window is modal over the
manager's footer, so it carries two more copies of the footer's
PackageDownloadBar (`download_bars`, which the screen renders from the same
state while the window is open): at the right end of the pagination row
(the pager stays centred) and docked bottom right in the detail header
card, on the stats line under the Version picker (_CardDownloadBar). Each
shows only while an install / switch downloads, like the footer's.

Every request runs on a job thread the screen provides (`run_job`, its
_run_job) so the window never blocks; the screen's own busy lock (one
mutating job at a time) is honored through `is_busy`.

A Required row opens that dependency's own page in place (the listing
detail job like a card's, the package taken from the row: Owner-Name, the
latest version - the declared one is only shown). A small history
(_history: (listing, tab) per page left that way) makes "← Back to
results", Esc and Backspace one level back: the previous package's page
(refetched, on the tab it was on) while there is one, else the results;
it is cleared whenever the results show.

Keys: Esc / Backspace go one level back - from the detail page to the
previous package's page (above) or the results (search, page and scroll
kept, like "← Back to results"); on the
browse page Esc closes the window, Backspace does nothing. In the search
box (any text field) Backspace edits the text as usual; Esc there clears
a query first (the Edit Config window's rule) and closes only when the
box is empty.
"""

import threading
import time
from datetime import datetime, timezone

import html
import re

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QObject, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor, QDesktopServices, QFont, QFontMetrics, QGuiApplication, QIcon, QImage, QImageReader, QPainter, QPainterPath, QPalette,
    QPixmap, QTextDocument,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from volt_py import icons, painters, theme, thunderstore as ts, thunderstore_browse as tb
from volt_py.applog import clip, log
from volt_py.screens.download_bar import LABEL_MAX_WIDTH, PackageDownloadBar
from volt_py.screens.flow_layout import FlowLayout

WINDOW_SIZE = (1400, 820)  # .modal.browse-mods
MODAL_GAP = 12  # .modal gap
COLUMNS = 4  # was the mockup's 5; 4 wider cards per row, sharing the grid's full width (user, 2026-09-29)
CARD_GAP = 12  # .card-grid gap
CARD_HEIGHT = 162  # 4 rows of 4 = a page (thunderstore_browse.PAGE_SIZE); the grid scrolls at the 820px minimum.
# 156 -> 162 in 3.2: the icon mat (+8) and the footer rule (+1 + 7 padding), less one layout gap (the
# description now takes the stretch) - the mockup's 160px card plus 2px of slack for font metrics
INITIAL_ORDERING = "most-downloaded"  # the sort the browser opens on (user, 2026-09-29; the mockup said Last updated)
CARD_PADDING = 10
CARD_FOOT_PAD = (7, 8)  # the footer's space above its button (under the rule) and the card's bottom padding (3.2)
ICON_PX = 40  # .card-icon
ICON_MAT = 4  # the card icon's mat around it: 1px edge + 3px (QLabel[role="browse-icon"][mat="true"]; 3.2)
ICON_RADIUS = 3  # the icon's corners inside the mat
DETAIL_ICON_PX = 96  # the header card's icon (on painters.ThumbFrame's mat, 3.3)
HEADER_PAD = 14  # the header card's padding
HEADER_THUMB_GAP = 16  # the mat's right edge -> the text column (3.3; was the icon's 16)
FACTS_PAD = 14  # the facts card's side padding: its rules run inset (3.3; were full-bleed)
DEP_ICON_PX = 56  # a Required row's icon
DESC_LINES = 3  # the card description is clamped to this many lines
SEARCH_DEBOUNCE_MS = 300
STRIP_HEIGHT = 36  # the recessed search / Category / Sort strip (3.2)
STRIP_DIVIDER = 20  # its 1px dividers' height
STRIP_KEY_PX, STRIP_KEY_GAP = 10, 10  # a strip combo's copper key (mono 600 caps, .14em) and its gap to the value
PAGER_KEY_PX = 10  # the pager's copper PAGE key (terminal caps, .14em)
PAGER_NUM_PX, PAGER_NUM_SPACING = 12, 0.06  # its mono "1 / 764" (.06em)
MONO_HTML = ", ".join(f"'{f}'" for f in theme.MONO_FONTS)  # the mono stack for a rich-text style="" attribute
ICON_WORKERS = 3
CLOSE_PX = 30  # .close-btn
VERSION_PICKER_WIDTH = 240  # the header's selector
RIGHT_COLUMN_WIDTH = 300  # the facts column (fixed on every window width; the left column flexes)
CHIP_GAP = 6
PAGE_JOB = "browse-list"
TABS = (("details", "Details"), ("required", "Required"), ("versions", "Versions"), ("changelog", "Changelog"), ("wiki", "Wiki"))
TAB_INDEX = {"details": 1, "required": 2, "versions": 3, "changelog": 4, "wiki": 5}  # tab_stack pages; 0 = the status page
WIKI_RAIL_WIDTH = 240  # the Wiki tab's page rail (the Help window's RAIL_WIDTH)
WIKI_ENTRY_ROOM = 44  # the rail's margins, an entry's padding and the rail's scrollbar: a title elides past the rest
IMAGE_MAX_HEIGHT = 1200  # a README image taller than this is scaled down (a whole-page banner never fills the box)
REFIT_MS = 150  # the README re-lays its images out this long after the last resize / image arrival
IMAGE_MAX_WIDTH = 1600  # shrink_image: a README image is cached and shown at most this wide (never upscaled)
IMAGE_MAX_PIXELS = 25_000_000  # shrink_image: a bigger bitmap (~100 MB decoded) is never decoded - skipped
JPEG_QUALITY = 85  # shrink_image's re-encode of an image without alpha (with alpha: PNG)
README_MIN_HEIGHT = 240  # the Details README well's floor: never squeezed below this by the block under it (0.6.31)
DEPS_PROBLEMS_SHOWN = 5  # the Details block lists at most this many problem dependencies, then "and N more"
AGE_MONTH_DAYS, AGE_YEAR_DAYS = 30, 365  # "Last updated": days -> green, months -> yellow, years -> red
AGE_COLORS = (theme.RDEP, theme.WARN, theme.DANGER)
BUTTON_TEXT_PADDING = 24  # the big Install button's horizontal padding + border, for fitting its text
INSTALLED_ICON_ROOM = 24  # the already-installed state's check icon (16) + its gap, and the 600 weight's extra width
# Thunderstore's own deprecated-package warning (the detail page's banner;
# the manager's details panel shows the same text).
DEPRECATED_BANNER = ("This mod is marked deprecated: its author may no longer look after it, so it may stop "
                     "working. Look for an alternative if you can.")  # 0.6.24 plain words


def clamp_text(text: str, fm, width: int, max_lines: int) -> str:
    """Greedy word wrap of `text` to `width` (font metrics `fm`), at most
    `max_lines` lines, the last one elided with an ellipsis when the text
    doesn't fit - the card description (CSS's flex: 1 overflow clip, done
    honestly). Returns the lines joined with newlines."""
    words = (text or "").split()
    if not words or max_lines < 1:
        return ""
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if current and fm.horizontalAdvance(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    if len(lines) > max_lines:
        rest = " ".join(lines[max_lines - 1:])
        lines = lines[:max_lines - 1] + [fm.elidedText(rest, Qt.TextElideMode.ElideRight, max(0, width))]
    return "\n".join(lines)


def install_label(name: str, missing: int, load_order: str) -> str:
    """The big button: "Install EpicLoot + 1 required mod to Vanilla+"."""
    extra = f" + {missing} required mod{'s' if missing != 1 else ''}" if missing else ""
    return f"Install {name}{extra} to {load_order}"


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def date_text(value, now: datetime | None = None) -> str:
    """A Thunderstore timestamp as "2026-09-24 (5 days ago)" / "(today)" /
    "(3 years ago)"; "-" when missing."""
    dt = _parse_iso(value)
    if dt is None:
        return "-"
    now = now or datetime.now(timezone.utc)
    days = max(0, (now - dt).days)
    if days < 1:
        ago = "today"
    elif days < 30:
        ago = f"{days} day{'s' if days != 1 else ''} ago"
    elif days < 365:
        months = days // 30
        ago = f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = days // 365
        ago = f"{years} year{'s' if years != 1 else ''} ago"
    return f"{dt.strftime('%Y-%m-%d')} ({ago})"


def age_color(value, now: datetime | None = None) -> str | None:
    """The "Last updated" tint: AGE_COLORS[0] under AGE_MONTH_DAYS, [1]
    under AGE_YEAR_DAYS, [2] beyond; None for a missing date."""
    dt = _parse_iso(value)
    if dt is None:
        return None
    days = max(0, ((now or datetime.now(timezone.utc)) - dt).days)
    return AGE_COLORS[0] if days < AGE_MONTH_DAYS else AGE_COLORS[1] if days < AGE_YEAR_DAYS else AGE_COLORS[2]


def age_html(value, now: datetime | None = None) -> str:
    """date_text with the "(N ... ago)" part in age_color, as rich text."""
    text = date_text(value, now)
    color = age_color(value, now)
    if color is None or " (" not in text:
        return text
    date, ago = text.split(" (", 1)
    return f'{date} <span style="color:{color}">({ago}</span>'


def fit_button_text(text: str, fm, width: int) -> tuple[str, bool]:
    """The big Install button's label, never clipped: the text as is when
    it fits `width`; else two lines split at the last " to " (or, for
    "<name> is already in <lo>", the last " in "; the load order on the
    second), each elided to fit (the name line in the middle, so
    "+ N dependencies" survives; the load order line on the right).
    Returns (label, changed)."""
    if fm.horizontalAdvance(text) <= width:
        return text, False
    head, sep, tail = text.rpartition(" to ")
    if not sep:
        head, sep, tail = text.rpartition(" in ")
    lines = [head, f"{sep.strip()} {tail}"] if sep else [text]
    fitted = [fm.elidedText(lines[0], Qt.TextElideMode.ElideMiddle, width)]
    if len(lines) > 1:
        fitted.append(fm.elidedText(lines[1], Qt.TextElideMode.ElideRight, width))
    return "\n".join(fitted), True


def render_markdown_html(markdown: str) -> str:
    """The README as one HTML document: split_html_blocks' markdown chunks
    through Qt's markdown importer (a scratch QTextDocument -> toHtml's
    body; each chunk first through thunderstore_browse.qt_markdown, so a
    tag-like "<rarity>" shows as text instead of hiding the prose after
    it), its HTML chunks as they are."""
    parts: list[str] = []
    for kind, text in tb.split_html_blocks(markdown):
        if kind == "html":
            parts.append(text)
        elif text.strip():
            doc = QTextDocument()
            doc.setMarkdown(tb.qt_markdown(text))  # a stray "<rarity>" would swallow the chunk's prose
            parts.append(_html_body(doc.toHtml()))
    return "\n".join(parts)


def _html_body(html: str) -> str:
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else html


def stats_text(downloads: int, ratings: int, size: int) -> str:
    """The header's stats line (rich text): "[download] 2,254,655  ·  [star]
    335 ratings  ·  31.2 MB", the drawn icons (icons.py; were the ⬇ / ★
    glyphs, which Windows drew as color emoji) in the line's --muted."""
    parts = [f"{icons.inline('download', theme.MUTED)} {tb.format_count(downloads)}",
             f"{icons.inline('star', theme.MUTED)} {tb.format_count(ratings)} rating{'s' if ratings != 1 else ''}"]
    if size:
        parts.append(tb.format_size(size))
    return "&nbsp; · &nbsp;".join(parts)


def set_installed_look(button: QPushButton, installed: bool) -> None:
    """Installed / already installed as a success state (theme.py's
    QPushButton[installed="true"]:disabled: an --ok tint, --ok text) with a
    drawn check; repolished only when it changes."""
    if bool(button.property("installed")) == installed:
        return
    button.setProperty("installed", installed)
    button.setIcon(icons.icon("check", theme.OK, theme.OK) if installed else QIcon())
    _repolish(button)


def link_html(url: str, text: str) -> str:
    return f'<a href="{url}" style="color:{theme.ACCENT}; text-decoration: none">{text}</a>'


def shown_url(url: str) -> str:
    return url.split("://", 1)[-1].removeprefix("www.").rstrip("/")


def rounded_pixmap(pixmap: QPixmap, size: int, radius: int = theme.RADIUS) -> QPixmap:
    """The icon scaled to size x size logical px with the card's corner
    radius (the mockup's border-radius on the icon placeholders), rendered
    at the app's device pixel ratio (3.2: was drawn at 1x and upscaled by
    Qt at 125%, soft)."""
    dpr = icons.app_dpr()
    side = max(1, round(size * dpr))
    scaled = pixmap.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(side, side)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, side, side), radius * dpr, radius * dpr)
    painter.setClipPath(path)
    painter.drawPixmap((side - scaled.width()) // 2, (side - scaled.height()) // 2, scaled)
    painter.end()
    out.setDevicePixelRatio(dpr)
    return out


class _IconLoader(QObject):
    """Fetches icons off the GUI thread: request(url) queues it (newest
    first - the page on screen beats one scrolled past), `loaded` brings
    the bytes back over a queued connection (b"" when the fetch failed).
    `fetch(key) -> bytes` replaces the download (0.6.26: the manager's
    rows pass mod_icons.load_icon over icon keys - disk only)."""

    loaded = Signal(str, object)  # url (or fetch's key), bytes

    def __init__(self, app_version, fetch=None) -> None:
        # No Qt parent on purpose: the workers keep this object alive until
        # they finish, so a late reply never lands on a deleted receiver.
        super().__init__()
        self._app_version = app_version
        self._fetch = fetch or (lambda url: tb.fetch_bytes(url, app_version))
        self._pending: list[str] = []
        self._cv = threading.Condition()
        self._stopped = False
        self._threads = [threading.Thread(target=self._work, name=f"icon-{i}", daemon=True) for i in range(ICON_WORKERS)]
        for t in self._threads:
            t.start()

    def request(self, url: str) -> None:
        with self._cv:
            if url in self._pending:
                self._pending.remove(url)
            self._pending.append(url)
            self._cv.notify()

    def clear(self) -> None:
        with self._cv:
            self._pending.clear()

    def stop(self) -> None:
        with self._cv:
            self._stopped = True
            self._pending.clear()
            self._cv.notify_all()

    def _work(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stopped:
                    self._cv.wait()
                if self._stopped:
                    return
                url = self._pending.pop()
            try:
                data = self._fetch(url)
            except (ts.ThunderstoreError, ValueError) as err:
                log(f"[browse] icon {url}: {err}")
                data = b""
            if not self._stopped:
                try:
                    self.loaded.emit(url, data)
                except RuntimeError:  # the window is gone
                    return


def shrink_image(data: bytes) -> bytes | None:
    """A fetched README image as it is cached and shown (load_images' shrink;
    runs on its worker threads - QImage / QImageReader are reentrant, no
    widget involved): decoded, scaled down smoothly to IMAGE_MAX_WIDTH (aspect
    kept, never up) and re-encoded - PNG when it has an alpha channel, else
    JPEG at JPEG_QUALITY. An image that needed no scaling keeps its own bytes
    when the re-encode isn't smaller. None: not decodable here (load_images
    decides whether to keep it); ValueError: bigger than IMAGE_MAX_PIXELS -
    checked from the header before the full decode (Qt's own allocation
    limit, 256 MB, backs it up for formats that don't say their size). Logs
    each image's decode / scale / encode time and bytes before -> after."""
    started = time.perf_counter()
    source = QBuffer()
    source.setData(QByteArray(data))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    size = reader.size()
    if size.isValid() and size.width() * size.height() > IMAGE_MAX_PIXELS:
        raise ValueError(f"{size.width()}x{size.height()} is too large to show (over {IMAGE_MAX_PIXELS // 1_000_000} megapixels)")
    image = reader.read()
    decoded = time.perf_counter()
    if image.isNull():
        log(f"[browse] image shrink: not decodable ({reader.errorString()}), {len(data)} bytes")
        return None
    width, height = image.width(), image.height()
    scaled = width > IMAGE_MAX_WIDTH
    if scaled:
        image = image.scaledToWidth(IMAGE_MAX_WIDTH, Qt.TransformationMode.SmoothTransformation)
    rescaled = time.perf_counter()
    kind = "PNG" if image.hasAlphaChannel() else "JPEG"
    target = QBuffer()
    target.open(QIODevice.OpenModeFlag.WriteOnly)
    saved = image.save(target, kind, -1 if kind == "PNG" else JPEG_QUALITY)
    encoded = target.data().data() if saved else b""
    finished = time.perf_counter()
    out = encoded if encoded and (scaled or len(encoded) < len(data)) else data
    log(f"[browse] image shrink: {width}x{height}" + (f" -> {image.width()}x{image.height()}" if scaled else "")
        + f", {kind if out is encoded else 'original kept'}, decode {(decoded - started) * 1000:.0f} ms, "
        f"scale {(rescaled - decoded) * 1000:.0f} ms, encode {(finished - rescaled) * 1000:.0f} ms, "
        f"{len(data)} -> {len(out)} bytes")
    return out


class _ImageFeed(QObject):
    """Brings README / changelog / wiki images from the background image
    steps (thunderstore_browse.load_images' workers) to the GUI thread:
    `arrived` (target, gen, url, bytes) over a queued connection - target
    "detail" or a wiki page id, gen the page's generation when the step
    started. _IconLoader's rules: no Qt parent (the workers keep it alive
    until they finish), nothing touched but the signal off the GUI thread."""

    arrived = Signal(object)


class _CardDownloadBar(PackageDownloadBar):
    """The detail header card's copy of the download bar (0.6.26): a child
    of the card kept out of its layout (nothing in the card moves), docked
    with its right edge on the card's right padding - under the Version
    picker - and centred on the stats line (`anchor`); its label is elided
    to the room right of the stats text, so the stats stay clear (the label
    gives way first; only a header card narrower than any real window,
    under ~650px, would bring the pill itself over them)."""

    def __init__(self, card: QFrame, anchor: QLabel) -> None:
        super().__init__(card)
        self._card, self._anchor = card, anchor
        card.installEventFilter(self)
        anchor.installEventFilter(self)

    def render(self, state, titles, *, copying: bool = False) -> None:
        super().render(state, titles)
        self._dock()

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self._dock()
        return False

    def _dock(self) -> None:
        stats = self._anchor.geometry()
        right = self._card.width() - HEADER_PAD
        room = right - (stats.left() + self._anchor.sizeHint().width() + HEADER_THUMB_GAP)
        fixed = self.sizeHint().width() - self.label.sizeHint().width()  # everything but the label
        self.label_max = max(0, min(LABEL_MAX_WIDTH, room - fixed))
        text = self.label.toolTip()
        self.label.setText(self.label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, self.label_max))
        self.adjustSize()
        self.move(right - self.width(), stats.center().y() - self.height() // 2)


class _ElidedLabel(QLabel):
    """One line, elided to the label's width (as the screen's _PathLine)."""

    def __init__(self, role: str | None = None, *, muted: bool = False) -> None:
        super().__init__()
        if role:
            self.setProperty("role", role)
        if muted:
            self.setProperty("muted", True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full = ""

    def set_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text if text else "")
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, width)))


class _ClampedLabel(QLabel):
    """Up to DESC_LINES wrapped lines, the last elided (clamp_text)."""

    def __init__(self, role: str, lines: int = DESC_LINES) -> None:
        super().__init__()
        self.setProperty("role", role)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._lines = lines
        self._full = ""

    def set_text(self, text: str) -> None:
        self._full = " ".join((text or "").split())
        # rich text, so Qt wraps the tooltip (a plain-text one is one screen-wide line)
        self.setToolTip(f"<p>{html.escape(self._full)}</p>" if self._full else "")
        self._clamp()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._clamp()

    def _clamp(self) -> None:
        fm = self.fontMetrics()
        self.setFixedHeight(fm.lineSpacing() * self._lines)
        self.setText(clamp_text(self._full, fm, self.contentsRect().width(), self._lines))


class _Card(QFrame):
    """One .card: icon | name / by author, description, ⬇ downloads | Install.
    A click anywhere but the button opens the detail page (`opened`).
    Steps 3.2 (Circuit): the icon on a --well mat, a hairline rule across the
    card above the footer, mono downloads, and a static raised hover - the
    QSS :hover wash + --border-hi edge, and the deeper cached shadow swapped
    in on enter / leave (painters.set_raised; the window's shadow host)."""

    opened = Signal(object)  # the listing dict
    install = Signal(object)

    def __init__(self, listing: dict) -> None:
        super().__init__()
        self.listing = listing
        self.setProperty("role", "browse-card")
        self.setFixedHeight(CARD_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(listing["full_name"])
        layout = QVBoxLayout(self)
        # no side padding here: the footer's rule runs the card's full width;
        # the head / description / footer rows carry CARD_PADDING themselves
        layout.setContentsMargins(0, CARD_PADDING, 0, CARD_FOOT_PAD[1])
        layout.setSpacing(6)  # .card gap
        head = QHBoxLayout()  # .card-head
        head.setContentsMargins(CARD_PADDING, 0, CARD_PADDING, 0)
        head.setSpacing(8)
        self.icon = QLabel()
        self.icon.setProperty("role", "browse-icon")
        self.icon.setProperty("mat", True)  # theme.py: the --well mat around the icon
        self.icon.setFixedSize(ICON_PX + 2 * ICON_MAT, ICON_PX + 2 * ICON_MAT)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name = _ElidedLabel("browse-name")
        self.name.set_text(listing["name"])
        self.author = _ElidedLabel("browse-small")
        self.author.set_text(f"by {listing['namespace']}")
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        self.deprecated_pill = None
        if listing.get("is_deprecated"):
            pill = self.deprecated_pill = QLabel("Deprecated")
            pill.setProperty("role", "browse-pill")
            pill.setProperty("state", "danger")
            name_row.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)
        name_row.addWidget(self.name, 1)
        names.addLayout(name_row)
        names.addWidget(self.author)
        names.addStretch(1)
        head.addLayout(names, 1)
        layout.addLayout(head)
        self.description = _ClampedLabel("browse-desc")
        self.description.setContentsMargins(CARD_PADDING, 0, CARD_PADDING, 0)
        self.description.set_text(listing["description"])
        layout.addWidget(self.description, 1, Qt.AlignmentFlag.AlignTop)  # it takes the card's slack
        footer = QFrame()  # .card-foot: space-between, under a full-width hairline (theme.py browse-card-foot)
        footer.setProperty("role", "browse-card-foot")
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(CARD_PADDING, CARD_FOOT_PAD[0], CARD_PADDING, 0)
        foot.setSpacing(8)
        self.downloads = QLabel(f"{icons.inline('download', theme.MUTED, 12)} {tb.format_count(listing['download_count'])}")
        self.downloads.setTextFormat(Qt.TextFormat.RichText)
        self.downloads.setProperty("role", "browse-dl")  # theme.py: mono 11px --muted
        self.downloads.setToolTip("Downloads")
        foot.addWidget(self.downloads)
        foot.addStretch(1)
        self.install_button = QPushButton("Install")
        self.install_button.setProperty("variant", "accent-outline")
        self.install_button.setAutoDefault(False)
        self.install_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.install_button.clicked.connect(lambda _=False: self.install.emit(self.listing))
        foot.addWidget(self.install_button)
        layout.addWidget(footer)

    def set_icon(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.icon.clear()
            return
        self.icon.setPixmap(rounded_pixmap(pixmap, ICON_PX, ICON_RADIUS))

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        painters.set_raised(self, True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        painters.set_raised(self, False)

    def set_install_state(self, text: str, enabled: bool) -> None:
        self.install_button.setText(text)
        self.install_button.setEnabled(enabled)
        set_installed_look(self.install_button, text == "Installed")
        if bool(self.property("installed")) != (text == "Installed"):  # the card's --ok edge (theme.py)
            self.setProperty("installed", text == "Installed")
            _repolish(self)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.opened.emit(self.listing)


class _DepRow(QFrame):
    """A Required tab row: `opened` (the row's dependency dict) on a left
    click, the hand cursor, the hover wash (theme.py browse-row:hover) - the
    result card's click, without its lift. Mouse only (the cards aren't
    focusable either)."""

    opened = Signal(object)

    def __init__(self, dep: dict) -> None:
        super().__init__()
        self.dep = dep
        self.setProperty("role", "browse-row")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(dep["full_name"])

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.opened.emit(self.dep)


class _Readme(QTextBrowser):
    """The README / changelog box: markdown (+ raw HTML, render_markdown_html),
    external links, and its images (`images`: url -> bytes, merged in by
    add_images as the background step brings them, 0.6.31) served through
    loadResource - Qt asks for each image at layout time, this answers from
    memory, never from the network, scaled to the box's width (never up;
    IMAGE_MAX_HEIGHT caps a tall one) and re-served after a resize or new
    images (the document is set again, REFIT_MS after the last one - a burst
    of arrivals is one re-layout - the scroll position kept). An image not
    there (yet, or ever) stays a blank box (Qt's default)."""

    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setOpenLinks(False)  # every click goes through _open_link: nothing navigates the box itself
        self.anchorClicked.connect(lambda url: self._open_link(url))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.images: dict[str, bytes] = {}
        self._decoded: dict[str, QImage] = {}  # url -> the native image
        self._wanted: set[str] = set()  # the image URLs this document shows (add_images takes only these)
        self._stale = False  # new images since the document was last set
        self._html = ""
        self._fit_width = 0  # the width the images were last scaled for
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(REFIT_MS)
        self._refit_timer.timeout.connect(lambda: self._refit())

    def set_markdown(self, markdown: str, images: dict[str, bytes] | None = None, *, fallback: str = "") -> None:
        self.images = dict(images or {})
        self._decoded = {}
        self._stale = False
        self._html = render_markdown_html(markdown) if markdown.strip() else ""
        self._wanted = set(tb.markdown_image_urls(markdown)) if self._html else set()
        self._fit_width = self._available_width()
        if self._html:
            self.setHtml(self._html)
        else:
            self.setPlainText(fallback.strip() or "No description.")
        self.verticalScrollBar().setValue(0)

    def add_images(self, images: dict[str, bytes]) -> None:
        """Images that just arrived: the ones this document shows (and doesn't
        have yet) are merged in and the document is set again REFIT_MS later
        (_refit; more arrivals meanwhile restart the wait)."""
        fresh = {url: data for url, data in images.items() if url in self._wanted and url not in self.images}
        if not fresh:
            return
        self.images.update(fresh)  # never decoded before (loadResource only decodes what images holds)
        self._stale = True
        self._refit_timer.start()

    def _open_link(self, url: QUrl) -> None:
        """An absolute link opens in the system browser (Qt's openExternalLinks
        rule: not file: / qrc:), "#section" scrolls to it, a relative one (a
        repo file, another wiki page) is ignored - Qt would load it into the
        box and blank the page."""
        if url.isRelative():
            if url.hasFragment() and not url.path():
                self.scrollToAnchor(url.fragment())
            else:
                log(f"browse: relative link not opened: {clip(url.toString())}")
        elif url.scheme() in ("file", "qrc"):
            log(f"browse: local link not opened: {clip(url.toString())}")
        else:
            QDesktopServices.openUrl(url)

    def _available_width(self) -> int:
        return max(50, self.viewport().width() - 2 * int(self.document().documentMargin()) - 2)

    def loadResource(self, kind: int, url: QUrl):
        key = url.toString()
        if key in self.images:
            image = self._decoded.get(key)
            if image is None:
                image = QImage.fromData(self.images[key])
                self._decoded[key] = image
            if not image.isNull():
                return self._fitted(image)
        return super().loadResource(kind, url)

    def _fitted(self, image: QImage) -> QImage:
        """Down to the box's width and IMAGE_MAX_HEIGHT, aspect kept; never up."""
        width = min(image.width(), self._fit_width or self._available_width())
        height = image.height() * width // max(1, image.width())
        if height > IMAGE_MAX_HEIGHT:
            height = IMAGE_MAX_HEIGHT
            width = image.width() * height // max(1, image.height())
        if width == image.width() and height == image.height():
            return image
        return image.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.images and self._html and self._available_width() != self._fit_width:
            self._refit_timer.start()

    def _refit(self) -> None:
        if not self._html or (not self._stale and self._available_width() == self._fit_width):
            return
        self._stale = False
        self._fit_width = self._available_width()
        scroll = self.verticalScrollBar().value()
        self.setHtml(self._html)  # the document's resource cache goes with it: loadResource scales again
        self.verticalScrollBar().setValue(scroll)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _status_page() -> tuple[QWidget, QLabel, QPushButton]:
    """A centered message + Retry (the tab body's loading / error page; the
    Wiki pane has its own)."""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addStretch(1)
    message = QLabel()
    message.setAlignment(Qt.AlignmentFlag.AlignCenter)
    message.setWordWrap(True)
    layout.addWidget(message)
    retry = QPushButton("Retry")
    retry.setAutoDefault(False)
    layout.addWidget(retry, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch(1)
    return page, message, retry


def _set_status(message: QLabel, retry: QPushButton, text: str, error: bool) -> None:
    message.setText(text)
    role = "modal-error" if error else None
    if message.property("role") != role or message.property("muted") != (not error):
        message.setProperty("role", role)
        message.setProperty("muted", not error)
        _repolish(message)
    retry.setVisible(error)


def _close_button() -> QPushButton:
    button = QPushButton()  # .close-btn 30x30, a drawn x (icons.py; was the ✕ glyph)
    button.setIcon(icons.icon("x"))
    button.setObjectName("browseClose")
    button.setFixedSize(CLOSE_PX, CLOSE_PX)
    button.setAutoDefault(False)
    button.setToolTip("Close")
    return button


def _well_shade() -> QWidget:
    """A recessed well's 7px top shade strip (theme.py QWidget#browseWellShade,
    the 3.1 details well's), laid over the well's top edge in its grid cell."""
    shade = QWidget()
    shade.setObjectName("browseWellShade")
    shade.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    shade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    shade.setFixedHeight(7)
    return shade


def _well(inner: QWidget) -> QFrame:
    """`inner` sunk into a recessed well (3.3: the README / changelog): the
    3.1 details well's frame (theme.py QFrame#browseWell) + its top shade."""
    well = QFrame()
    well.setObjectName("browseWell")
    cell = QGridLayout(well)
    cell.setContentsMargins(1, 1, 1, 1)
    cell.setSpacing(0)
    cell.addWidget(inner, 0, 0)
    cell.addWidget(_well_shade(), 0, 0, Qt.AlignmentFlag.AlignTop)
    return well


def _strip_divider() -> QFrame:
    """A 1px divider between two fields of the recessed filter strip (3.2)."""
    line = QFrame()
    line.setProperty("role", "strip-divider")
    line.setFixedSize(1, STRIP_DIVIDER)
    return line


class _KeyCombo(QComboBox):
    """A filter-strip combo (3.2 tweak "copper keys in combos", 0.5.10): the
    items keep their "Category: x" / "Sort: x" text (popup, type-ahead, the
    screen's logic unchanged); only the closed label is painted split - the
    prefix as a copper terminal key (mono 10px 600 caps, .14em), the value in
    the combo's own --text. Frame, hover fill, arrow, focus and the popup are
    still drawn by the style (the QSS strip rules)."""

    def __init__(self, key: str) -> None:
        super().__init__()
        self._key = key
        self._key_font = QFont(list(theme.MONO_FONTS))
        self._key_font.setPixelSize(STRIP_KEY_PX)
        self._key_font.setWeight(QFont.Weight.DemiBold)
        self._key_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, round(STRIP_KEY_PX * painters.TERMINAL_KEY_SPACING, 2))
        self.setAccessibleName(key)

    def _key_width(self) -> int:
        return QFontMetrics(self._key_font).horizontalAdvance(self._key.upper()) + STRIP_KEY_GAP

    def sizeHint(self) -> QSize:  # the key + gap replace the "Key: " prefix in the width
        hint = super().sizeHint()
        extra = self._key_width() - self.fontMetrics().horizontalAdvance(f"{self._key}: ")
        return QSize(hint.width() + max(0, extra), hint.height())

    def paintEvent(self, _event) -> None:
        painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        value = opt.currentText.removeprefix(f"{self._key}: ")
        opt.currentText = ""
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        field = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, opt, QStyle.SubControl.SC_ComboBoxEditField, self)
        # key and value on ONE baseline, the value's (vertically centred as the
        # style would): two AlignVCenter boxes of different font sizes put the
        # 10px caps ~2px above the 13px value (3.4 hardware review)
        metrics = self.fontMetrics()
        baseline = field.top() + (field.height() - metrics.height()) // 2 + metrics.ascent()
        painter.setFont(self._key_font)
        painter.setPen(QColor(theme.SIGNAL if self.isEnabled() else theme.MUTED))
        painter.drawText(QPoint(field.left(), baseline), self._key.upper())
        left = field.left() + self._key_width()
        painter.setFont(self.font())
        painter.setPen(opt.palette.color(QPalette.ColorRole.ButtonText))
        painter.drawText(QPoint(left, baseline), metrics.elidedText(value, Qt.TextElideMode.ElideRight, max(0, field.right() + 1 - left)))

    def showPopup(self) -> None:
        # 3.4 decision 4 (0.5.12 amendment): the popup as wide as its longest
        # item. Qt widens it only by the combo's own text metrics, leaving out
        # the ::item padding, the popup border and the scrollbar, so the longest
        # category names elided in the middle; a view minimum width only ever
        # widens it (never below the combo), recomputed per open (categories reload).
        view = self.view()
        need = view.sizeHintForColumn(0) + 2 * view.frameWidth()
        if self.count() > self.maxVisibleItems():
            need += view.verticalScrollBar().sizeHint().width()
        view.setMinimumWidth(need)
        super().showPopup()


def _spaced_font(size_px: int, spacing_em: float):
    """Letter-spacing only (QSS can't set it), on an otherwise empty font so
    the label's QSS family / size / colour still apply (as painters.terminal_font)."""
    from PySide6.QtGui import QFont

    font = QFont()
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, round(size_px * spacing_em, 2))
    return font


def _panel(role: str = "browse-panel") -> QFrame:
    frame = QFrame()
    frame.setProperty("role", role)
    return frame


def _scroll(inner: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setObjectName("browseTabScroll")
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(inner)
    scroll.viewport().setAutoFillBackground(False)
    inner.setAutoFillBackground(False)
    return scroll


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.hide()
            widget.deleteLater()


class BepInExBrowseWindow(QDialog):
    def __init__(self, game, game_name: str, load_order_name: str, *, installed, framework: str | None,
                 run_job, install, switch_version, is_busy, app_version=None, app_root=None,
                 parent: QWidget | None = None) -> None:
        """`game`: the ThunderstoreGame (community slug). `installed()` ->
        the open load order's full_name -> entry dict (read live, it grows
        with every install; each entry's "version" is what's on disk);
        `framework`: its framework's full_name. `run_job(name, fn,
        on_done)`: the screen's _run_job. `install(ref, on_done, parent)`:
        the screen's install job (on_done({"ok": ...} or {"error": ...})
        after the screen refreshed); `switch_version(full_name, version |
        None, on_done, parent)`: its in-place re-install at that version
        (None = the latest). `is_busy()`: the screen's mutating-job lock.
        `app_root`: the game's app root, for the README image cache (None:
        no disk cache)."""
        super().__init__(parent)
        self.setObjectName("browseMods")
        self.setWindowTitle(f"Browse Thunderstore Mods - {game_name}")
        self.setModal(True)
        self.game = game
        self.game_name = game_name
        self.load_order_name = load_order_name
        self._installed = installed
        self._framework = framework
        self._run_job = run_job
        self._install = install
        self._switch_version = switch_version
        self._is_busy = is_busy
        self.app_version = app_version
        self._app_root = app_root
        self._closed = False
        # browse state
        self._query = ""
        self._ordering = INITIAL_ORDERING
        self._category = None  # a category id, or None for all
        self._deprecated = False  # Show deprecated / Show NSFW: include them (session-only, off on open)
        self._nsfw = False
        self._page = 1
        self._pages = 1
        self._gen = 0  # bumped per listing request; a reply from an older one is dropped
        self._page_cache: dict[tuple, dict] = {}  # (query, ordering, category, deprecated, nsfw, page) -> PagedListing.page result
        self._listings: dict[tuple, tb.PagedListing] = {}  # (query, ordering, category, deprecated, nsfw) -> its PagedListing
        self._cards: list[_Card] = []
        self._categories: list[dict] = []
        self._installing: str | None = None  # full_name of the install / switch in flight
        self._installing_version: str | None = None  # the version a switch is heading for (None = an install / the latest)
        # detail state
        self._detail_listing: dict | None = None  # the card's listing (namespace / name / icon_url / ...)
        self._detail: dict | None = None  # fetch_listing_detail's dict (the LATEST version: the right column)
        self._detail_gen = 0
        self._history: list[tuple[dict, str]] = []  # (listing, tab) per page left via a Required row; Back pops
        self._versions: list[dict] = []  # fetch_versions rows, newest first
        self._version: str | None = None  # the selected version (the header's picker)
        self._version_meta: dict | None = None  # fetch_version of the selected version
        self._chain: dict | None = None  # dependency_chain for the selected version (None while its step runs)
        self._chain_error: str | None = None  # that step's failure, shown in the block until the next page / version
        self._pkg_cache: dict[str, dict] = {}  # full_name -> fetch_package, for the chain (dies with the window)
        self._has_changelog = False
        self._wiki: list[dict] = []  # the package's wiki pages [{id, title}], rail order; [] = no wiki (tab hidden)
        self._wiki_pages: dict[str, dict] = {}  # page id -> {markdown, images}, this package's pages fetched so far
        self._wiki_page: str | None = None  # the page picked in the rail (None until the tab is first opened)
        self._wiki_gen = 0  # bumped per page request / package; an older reply is dropped
        self._wiki_buttons: dict[str, QPushButton] = {}
        self._tab = "details"
        self._version_buttons: list[tuple[str, QPushButton]] = []  # Versions tab: (version, its Install)
        self._dep_icons: list[tuple[str, QLabel]] = []  # Required tab: (icon_url, label)
        # icons: url -> QPixmap (null when the fetch failed), session-lived
        self._icons: dict[str, QPixmap] = {}
        self._icon_loader = _IconLoader(app_version)
        self._icon_loader.loaded.connect(self._on_icon, Qt.ConnectionType.QueuedConnection)
        self._image_feed = _ImageFeed()
        self._image_feed.arrived.connect(self._on_image, Qt.ConnectionType.QueuedConnection)

        layout = QVBoxLayout(self)  # .modal: padding 16px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_browse_page())
        detail_page = self._build_detail_page()
        self.stack.addWidget(detail_page)
        # Circuit shadows (painters.py: cached 9-slices painted behind them, no
        # effects): the result cards, from the grid's viewport (so a card's
        # shadow clips with the scrolled content), and the detail page's
        # panels (header card, tab body, facts, categories).
        painters.install_shadows(self.grid_scroll.viewport(), lambda: self._cards)
        painters.install_shadows(detail_page, [f for f in detail_page.findChildren(QFrame)
                                               if f.property("role") == "browse-panel"])
        layout.addWidget(self.stack, 1)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(lambda: self._search_settled())
        self.search.textChanged.connect(lambda _text: self._search_timer.start())
        self.category_combo.currentIndexChanged.connect(lambda _i: self._filters_changed())
        self.sort_combo.currentIndexChanged.connect(lambda _i: self._filters_changed())
        self.prev_button.clicked.connect(lambda _=False: self._turn_page(-1))
        self.next_button.clicked.connect(lambda _=False: self._turn_page(1))
        self.back_button.clicked.connect(lambda _=False: self._go_back())
        self.version_combo.currentIndexChanged.connect(lambda _i: self._version_changed())
        self.detail_install_button.clicked.connect(lambda _=False: self._install_from_detail())
        self.copy_button.clicked.connect(lambda _=False: self._copy_package_name())
        self.retry_button.clicked.connect(lambda _=False: self._retry_detail())
        self.wiki_retry.clicked.connect(lambda _=False: self._retry_wiki())
        self.close_button.clicked.connect(lambda _=False: self.reject())
        self.show_deprecated.toggled.connect(lambda _on: self._filters_changed())
        self.show_nsfw.toggled.connect(lambda _on: self._filters_changed())
        self.detail_close_button.clicked.connect(lambda _=False: self.reject())

        # the manager screen renders these with its own footer bar (_render_dl), same state (0.6.26)
        self.download_bars = (self.download_bar, self.detail_download_bar)
        log(f"browse window opened ({game.community}, load order {load_order_name!r})")
        if app_root:  # the README image cache's size cap, off the GUI thread (0.6.31)
            self._run_job("browse-image-cache-prune", lambda report: tb.prune_image_cache(app_root), lambda payload: None)
        self.search.setFocus()
        self._load_categories()
        self._load_page()

    # ---- layout: the Browse page ----
    def _build_browse_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(MODAL_GAP)
        header = QHBoxLayout()  # .validation-head
        header.setSpacing(8)
        title = QLabel("Browse Thunderstore Mods")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.show_deprecated = QPushButton("Show deprecated")
        self.show_nsfw = QPushButton("Show NSFW")
        for button in (self.show_deprecated, self.show_nsfw):
            button.setProperty("variant", "config-filter")  # theme.py: the Edit Config Filter toggle's checked look
            button.setIcon(icons.checkbox_icon())  # 3.2: a check box glyph, so "on" isn't carried by the fill alone
            button.setCheckable(True)
            button.setAutoDefault(False)
            header.addWidget(button)
        self.show_deprecated.setToolTip("Include deprecated mods in the results")
        self.show_nsfw.setToolTip("Include mods marked NSFW in the results")
        self.close_button = _close_button()
        header.addWidget(self.close_button)
        layout.addLayout(header)

        # .filter-row as one recessed strip (3.2): the same three fields, in the
        # same order, inside a --well frame (theme.py QFrame#browseFilterStrip:
        # the 3.1 well + its 7px top shade) that shows their hover / focus
        # edges; a copper ">" prompt, 1px dividers between the fields
        self.filter_strip = QFrame()
        self.filter_strip.setObjectName("browseFilterStrip")
        self.filter_strip.setProperty("fieldFocus", False)  # not "focus": QWidget's read-only Q_PROPERTY (hasFocus) - setProperty on it is a no-op
        self.filter_strip.setFixedHeight(STRIP_HEIGHT)
        strip_cell = QGridLayout(self.filter_strip)
        strip_cell.setContentsMargins(1, 1, 1, 1)
        strip_cell.setSpacing(0)
        filters = QHBoxLayout()
        filters.setContentsMargins(0, 0, 4, 0)
        filters.setSpacing(0)
        prompt = QLabel(">")
        prompt.setProperty("role", "strip-prompt")
        filters.addWidget(prompt)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods...")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        filters.addWidget(_strip_divider(), 0, Qt.AlignmentFlag.AlignVCenter)
        self.category_combo = _KeyCombo("Category")  # copper CATEGORY key + value
        self.category_combo.addItem("Category: All", None)
        self.category_combo.setMinimumWidth(180)
        filters.addWidget(self.category_combo)
        filters.addWidget(_strip_divider(), 0, Qt.AlignmentFlag.AlignVCenter)
        self.sort_combo = _KeyCombo("Sort")
        for value, label in tb.ORDERINGS:
            self.sort_combo.addItem(f"Sort: {label}", value)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(INITIAL_ORDERING)))
        self.sort_combo.setMinimumWidth(180)
        filters.addWidget(self.sort_combo)
        for field in (self.search, self.category_combo, self.sort_combo):
            field.setProperty("strip", True)  # theme.py: frameless inside the strip
            field.installEventFilter(self)  # focus in / out -> the strip's [focus] edge
        strip_cell.addLayout(filters, 0, 0)
        strip_cell.addWidget(_well_shade(), 0, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self.filter_strip)

        cell = QGridLayout()  # the grid with the loading / error / empty message laid over it
        cell.setContentsMargins(0, 0, 0, 0)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setObjectName("browseGrid")
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_widget = QWidget()
        self.grid = QGridLayout(self.grid_widget)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(CARD_GAP)
        self.grid.setVerticalSpacing(CARD_GAP)
        for column in range(COLUMNS):
            self.grid.setColumnStretch(column, 1)
        self.grid_scroll.setWidget(self.grid_widget)
        self.grid_scroll.viewport().setAutoFillBackground(False)
        self.grid_widget.setAutoFillBackground(False)
        cell.addWidget(self.grid_scroll, 0, 0)
        self.message = QLabel()
        self.message.setProperty("muted", True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setWordWrap(True)
        self.message.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.message.setVisible(False)
        cell.addWidget(self.message, 0, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(cell, 1)

        pagination = QHBoxLayout()  # .pagination: centered, gap 16
        pagination.setSpacing(16)
        pagination.addStretch(1)
        self.prev_button = QPushButton("‹ Prev")
        self.next_button = QPushButton("Next ›")
        for button in (self.prev_button, self.next_button):
            button.setProperty("variant", "browse-page")
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        # the counter (3.2): "PAGE  1 / 764" - a copper key and mono numbers
        # in a small well (theme.py QFrame#browsePager)
        self.pager_box = QFrame()
        self.pager_box.setObjectName("browsePager")
        pager = QHBoxLayout(self.pager_box)
        pager.setContentsMargins(12, 4, 12, 4)
        pager.setSpacing(6)
        pager_key = QLabel("Page")
        pager_key.setProperty("role", "pager-key")
        pager_key.setFont(painters.terminal_font(PAGER_KEY_PX, painters.TERMINAL_KEY_SPACING))
        pager.addWidget(pager_key)
        self.page_label = QLabel("")
        self.page_label.setProperty("role", "pager-num")
        self.page_label.setFont(_spaced_font(PAGER_NUM_PX, PAGER_NUM_SPACING))
        pager.addWidget(self.page_label)
        pagination.addWidget(self.prev_button)
        pagination.addWidget(self.pager_box)
        pagination.addWidget(self.next_button)
        # 0.6.26: the manager's download bar at the row's right end while an install runs; its
        # box takes the trailing stretch's place (same stretch), so the pager stays centred
        bar_box = QHBoxLayout()
        bar_box.setContentsMargins(0, 0, 0, 0)
        bar_box.addStretch(1)
        self.download_bar = PackageDownloadBar()
        self.download_bar.setVisible(False)
        bar_box.addWidget(self.download_bar, 0, Qt.AlignmentFlag.AlignVCenter)
        pagination.addLayout(bar_box, 1)
        self.pagination = QWidget()
        self.pagination.setLayout(pagination)
        layout.addWidget(self.pagination)
        return page

    # ---- layout: the Detail page (the signed-off Thunderstore-style page) ----
    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(MODAL_GAP)
        header = QHBoxLayout()
        header.setSpacing(8)
        self.back_button = QPushButton("← Back to results")
        self.back_button.setAutoDefault(False)
        header.addWidget(self.back_button)
        header.addStretch(1)
        self.detail_close_button = _close_button()
        header.addWidget(self.detail_close_button)
        layout.addLayout(header)
        self.detail_deprecated = QLabel(DEPRECATED_BANNER)
        self.detail_deprecated.setProperty("role", "config-banner")  # theme.py: --warn on a 14% --warn wash
        self.detail_deprecated.setWordWrap(True)
        self.detail_deprecated.setVisible(False)
        layout.addWidget(self.detail_deprecated)

        body = QHBoxLayout()  # left: header card + tabs | right: the facts column
        body.setSpacing(MODAL_GAP)
        left = QVBoxLayout()
        left.setSpacing(MODAL_GAP)
        left.addWidget(self._build_header_card())
        left.addWidget(self._build_tab_bar())
        left.addWidget(self._build_tab_body(), 1)
        body.addLayout(left, 1)
        body.addWidget(self._build_right_column())
        layout.addLayout(body, 1)
        return page

    def _build_header_card(self) -> QFrame:
        card = _panel()
        row = QHBoxLayout(card)
        # 3.3: the icon sits on 3.1's framed mat (painters.ThumbFrame: shadow,
        # --well mat, copper corner ticks), a fixed box so nothing jumps while
        # it loads (the bare mat meanwhile). The frame's own margins hold its
        # ticks + shadow, so the row's left / top / bottom margins shrink by
        # them and the mat's edge lands where the icon's was (14px in); the
        # text column and the version picker keep their 14px top.
        m_left, m_top, m_right, m_bottom = painters.THUMB_MARGINS
        row.setContentsMargins(HEADER_PAD - m_left, HEADER_PAD - m_top, HEADER_PAD, HEADER_PAD - m_bottom)
        row.setSpacing(HEADER_THUMB_GAP - m_right)
        self.detail_icon = painters.ThumbFrame(empty_mat=True)
        chrome_w, chrome_h = painters.thumb_chrome()
        self.detail_icon.setFixedSize(DETAIL_ICON_PX + chrome_w, DETAIL_ICON_PX + chrome_h)
        self.detail_icon.set_image(None, DETAIL_ICON_PX, DETAIL_ICON_PX)
        row.addWidget(self.detail_icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setContentsMargins(0, m_top, 0, m_bottom)
        names.setSpacing(6)
        self.detail_name = _ElidedLabel("browse-title")
        self.detail_description = QLabel()
        self.detail_description.setProperty("muted", True)
        self.detail_description.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_description.setWordWrap(True)
        self.detail_links = QLabel()  # "👥 author   🔗 website" - both open the browser
        self.detail_links.setTextFormat(Qt.TextFormat.RichText)
        self.detail_links.setOpenExternalLinks(True)
        self.detail_links.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.detail_stats = QLabel()  # the stats line: downloads · ratings · size (stats_text, rich text)
        self.detail_stats.setProperty("role", "browse-stats")  # theme.py: mono 12px --muted (3.3)
        self.detail_stats.setTextFormat(Qt.TextFormat.RichText)
        names.addWidget(self.detail_name)
        names.addWidget(self.detail_description)
        names.addWidget(self.detail_links)
        names.addWidget(self.detail_stats)
        names.addStretch(1)
        row.addLayout(names, 1)
        # 0.6.26: the download bar's detail copy, docked bottom right on the stats line (_CardDownloadBar)
        self.detail_download_bar = _CardDownloadBar(card, self.detail_stats)
        self.detail_download_bar.setVisible(False)
        self.version_combo = QComboBox()  # top-right: drives Install, Required, Changelog
        self.version_combo.setFixedWidth(VERSION_PICKER_WIDTH)
        self.version_combo.setEnabled(False)
        picker = QVBoxLayout()  # only to keep the picker's 14px top (the row's top margin is the frame's)
        picker.setContentsMargins(0, m_top, 0, 0)
        picker.addWidget(self.version_combo)
        picker.addStretch(1)
        row.addLayout(picker)
        return card

    def _build_tab_bar(self) -> QWidget:
        # A bare row widget (no margins, fixed height: the same geometry as the
        # layout it used to be) so the sliding underline has its own overlay host.
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        bar = QHBoxLayout(row)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(0)  # 3.3: the tabs' bottom edges are the strip's rule, unbroken
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, label in TABS:
            button = QPushButton(label)
            button.setProperty("variant", "browse-tab")
            button.setAutoDefault(False)
            button.clicked.connect(lambda _=False, key=key: self._select_tab(key, animate=True))
            bar.addWidget(button)
            self.tab_buttons[key] = button
        rule = QFrame()  # the rest of the strip's 1px rule, to the right edge (theme.py QFrame#browseTabRule)
        rule.setObjectName("browseTabRule")
        bar.addWidget(rule, 1)
        # the selected tab's --accent underline, slid between tabs (phase 4 M2;
        # the selected button's own QSS underline is transparent)
        self.tab_indicator = painters.TabIndicator(row, self._tab_band)
        return row

    def _tab_band(self):
        """The selected tab button's box in the tab row (TabIndicator), None while hidden."""
        button = self.tab_buttons.get(self._tab)
        return button.geometry() if button is not None and button.isVisible() else None

    def _build_tab_body(self) -> QFrame:
        frame = _panel()
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(14, 12, 14, 12)
        self.tab_stack = QStackedWidget()
        outer.addWidget(self.tab_stack)
        # 0: the status page (loading / error + Retry)
        status, self.detail_message, self.retry_button = _status_page()
        self.tab_stack.addWidget(status)
        # 1: Details = the README over the dependency block
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(10)
        self.readme = _Readme("browseReadme")
        readme_well = _well(self.readme)  # 3.3: the README sunk into a recessed well
        readme_well.setMinimumHeight(README_MIN_HEIGHT)  # 0.6.31: never squeezed to nothing by the block below
        details_layout.addWidget(readme_well, 1)
        divider = QFrame()
        divider.setObjectName("browseDivider")
        divider.setFixedHeight(1)
        details_layout.addWidget(divider)
        # the dependency block (3.3): a REQUIRES terminal label (side rule)
        # over a muted sub-line - what the block holds, or its state
        self.deps_title = painters.TerminalLabel("Requires", rule="side")
        details_layout.addWidget(self.deps_title)
        self.deps_label = QLabel()
        self.deps_label.setProperty("role", "browse-dep-sub")
        details_layout.addWidget(self.deps_label)
        self.deps_box = QWidget()
        self.deps_layout = QVBoxLayout(self.deps_box)
        self.deps_layout.setContentsMargins(0, 0, 0, 0)
        self.deps_layout.setSpacing(0)
        details_layout.addWidget(self.deps_box)
        self.tab_stack.addWidget(details)
        # 2: Required = rich rows
        required = QWidget()
        self.required_layout = QVBoxLayout(required)
        self.required_layout.setContentsMargins(0, 0, 0, 0)
        self.required_layout.setSpacing(8)
        self.tab_stack.addWidget(_scroll(required))
        # 3: Versions = a table of rows
        versions = QWidget()
        self.versions_layout = QVBoxLayout(versions)
        self.versions_layout.setContentsMargins(0, 0, 0, 0)
        self.versions_layout.setSpacing(0)
        self.tab_stack.addWidget(_scroll(versions))
        # 4: Changelog (in the README's well too)
        self.changelog = _Readme("browseReadme")
        self.tab_stack.addWidget(_well(self.changelog))
        # 5: Wiki = the page rail (the Help window's list: #helpRail, help-entry
        # buttons) beside the selected page in the README's well; the pane's own
        # loading / error page in front of it
        wiki = QWidget()
        wiki_row = QHBoxLayout(wiki)
        wiki_row.setContentsMargins(0, 0, 0, 0)
        wiki_row.setSpacing(8)
        rail = QWidget()
        self.wiki_rail = QVBoxLayout(rail)
        self.wiki_rail.setContentsMargins(4, 4, 4, 4)
        self.wiki_rail.setSpacing(4)
        rail_scroll = _scroll(rail)
        rail_scroll.setObjectName("helpRail")
        rail_scroll.setFixedWidth(WIKI_RAIL_WIDTH)
        wiki_row.addWidget(rail_scroll)
        self.wiki_stack = QStackedWidget()
        wiki_status, self.wiki_message, self.wiki_retry = _status_page()
        self.wiki_stack.addWidget(wiki_status)
        self.wiki_readme = _Readme("browseReadme")
        self.wiki_stack.addWidget(_well(self.wiki_readme))
        wiki_row.addWidget(self.wiki_stack, 1)
        self.tab_stack.addWidget(wiki)
        return frame

    def _build_right_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(RIGHT_COLUMN_WIDTH)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(MODAL_GAP)
        self.detail_install_button = QPushButton("Install")
        self.detail_install_button.setProperty("variant", "primary")
        self.detail_install_button.setProperty("big", True)
        self.detail_install_button.setAutoDefault(False)
        layout.addWidget(self.detail_install_button)
        # the package-name copy box
        copybox = QFrame()
        copybox.setObjectName("browseCopyBox")
        copy_row = QHBoxLayout(copybox)
        copy_row.setContentsMargins(0, 0, 0, 0)
        copy_row.setSpacing(0)
        self.package_name_edit = QLineEdit()
        self.package_name_edit.setObjectName("browsePackageName")
        self.package_name_edit.setReadOnly(True)
        copy_row.addWidget(self.package_name_edit, 1)
        self.copy_button = QPushButton()  # a drawn copy icon (icons.py; was the ⧉ glyph)
        self.copy_button.setIcon(icons.icon("copy"))
        self.copy_button.setObjectName("browseCopy")
        self.copy_button.setAutoDefault(False)
        self.copy_button.setToolTip("Copy the package name")
        copy_row.addWidget(self.copy_button)
        layout.addWidget(copybox)
        # the facts rows
        # the facts as a terminal table (3.3): a PACKAGE label, copper
        # terminal-caps keys (the details-key role), mono values
        facts = _panel()
        rows = QVBoxLayout(facts)
        rows.setContentsMargins(FACTS_PAD, 10, FACTS_PAD, 4)
        rows.setSpacing(0)
        package = painters.TerminalLabel("Package", rule="side")
        package.setProperty("size", "pane")  # theme.py: the pane-title size (11px), .16em
        package.setFont(painters.terminal_font(painters.TERMINAL_PANE_PX, painters.TERMINAL_SPACING))
        package.setContentsMargins(0, 0, 0, 4)
        rows.addWidget(package)
        self.fact_values: dict[str, QLabel] = {}
        for key, title in (("latest", "Latest version"), ("updated", "Last updated"), ("uploaded", "First uploaded"),
                           ("downloads", "Downloads"), ("likes", "Likes"), ("size", "Size"), ("dependants", "Dependants")):
            row = QFrame()
            row.setProperty("role", "browse-fact")
            row.setProperty("last", key == "dependants")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 8, 0, 8)
            row_layout.setSpacing(8)
            label = QLabel(title)
            label.setProperty("role", "details-key")  # theme.py: copper mono 11px 600
            label.setFont(painters.terminal_font(painters.TERMINAL_KEY_PX, painters.TERMINAL_KEY_SPACING))
            value = QLabel("-")
            value.setProperty("role", "browse-fact-value")
            value.setTextFormat(Qt.TextFormat.RichText if key in ("dependants", "updated") else Qt.TextFormat.PlainText)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            # a long value wraps under itself (right-aligned) instead of being
            # clipped at the left: "2021-04-30 (5 years ago)" didn't fit the
            # 300px column beside FIRST UPLOADED (3.4 hardware review)
            value.setWordWrap(True)
            if key == "dependants":
                value.setOpenExternalLinks(True)
                value.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
            row_layout.addWidget(label)
            row_layout.addWidget(value, 1)
            rows.addWidget(row)
            self.fact_values[key] = value
        layout.addWidget(facts)
        # categories
        cats = _panel()
        cats_layout = QVBoxLayout(cats)
        cats_layout.setContentsMargins(14, 12, 14, 12)
        cats_layout.setSpacing(8)
        title = painters.TerminalLabel("Categories", rule=False)  # a Circuit terminal label (role pane-title)
        cats_layout.addWidget(title)
        self.chips_box = QWidget()
        self.chips_layout = FlowLayout(self.chips_box, horizontal_spacing=CHIP_GAP, vertical_spacing=CHIP_GAP, center_rows=False)
        cats_layout.addWidget(self.chips_box)
        layout.addWidget(cats)
        layout.addStretch(1)
        return column

    # ---- the listing ----
    def _filters_changed(self) -> None:
        self._category = self.category_combo.currentData()
        self._ordering = self.sort_combo.currentData() or INITIAL_ORDERING
        self._deprecated = self.show_deprecated.isChecked()
        self._nsfw = self.show_nsfw.isChecked()
        log(f"browse: filters -> category={self._category}, {self._ordering}, deprecated={self._deprecated}, nsfw={self._nsfw}")
        self._page = 1
        self._load_page()

    def _search_settled(self) -> None:
        query = self.search.text().strip()
        if query == self._query:
            return
        self._query = query
        self._page = 1
        self._load_page()

    def _turn_page(self, step: int) -> None:
        page = self._page + step
        if page < 1 or page > self._pages:
            return
        self._page = page
        self._load_page()

    def _load_categories(self) -> None:
        community, app_version = self.game.community, self.app_version

        def done(payload: dict) -> None:
            if self._closed:
                return
            if "error" in payload:
                log(f"browse: categories unavailable: {payload['error']}")
                self.category_combo.setToolTip(f"Categories unavailable: {payload['error']}")
                return
            self._categories = payload["ok"]
            current = self.category_combo.currentData()
            self.category_combo.blockSignals(True)
            self.category_combo.clear()
            self.category_combo.addItem("Category: All", None)
            for c in self._categories:
                self.category_combo.addItem(f"Category: {c['name']}", c["id"])
            self.category_combo.setCurrentIndex(max(0, self.category_combo.findData(current)))
            self.category_combo.blockSignals(False)

        self._run_job("browse-categories", lambda report: tb.list_categories(community, app_version), done)

    def _load_page(self) -> None:
        key = (self._query, self._ordering, self._category, self._deprecated, self._nsfw, self._page)
        painters.stop_fades(self.grid_scroll.parentWidget())  # a newer load: end a running arrival fade, no ghost
        self._gen += 1
        gen = self._gen
        cached = self._page_cache.get(key)
        if cached is not None:
            log(f"browse: page {self._page} from the window's cache (q={self._query!r}, {self._ordering}, "
                f"category={self._category}, deprecated={self._deprecated}, nsfw={self._nsfw})")
            self._show_page(cached)
            return
        self._clear_cards()
        self._show_message("Loading...")
        self._set_pagination(False)
        query, ordering, category, deprecated, nsfw, page = key
        listing = self._listings.get(key[:5])
        if listing is None:
            listing = self._listings[key[:5]] = tb.PagedListing(
                self.game.community, query=query, ordering=ordering, category=category,
                deprecated=deprecated, nsfw=nsfw, app_version=self.app_version)

        def job(report):
            return listing.page(page)

        def done(payload: dict) -> None:
            if self._closed or gen != self._gen:
                return  # superseded by a newer request
            if "error" in payload:
                self._show_message(payload["error"], error=True)
                self.pagination.setVisible(False)
                return
            result = payload["ok"]
            if not result["results"] and result["page"] > result["pages"]:
                self._page = result["pages"]  # the count shrank under us: show the real last page
                self._load_page()
                return
            self._page_cache[key] = result
            # the cards replace "Loading..." under a MOTION_FAST crossfade (a cached page stays instant)
            painters.crossfade(self.grid_scroll.parentWidget(), lambda: self._show_page(result),
                               theme.MOTION_FAST, self.grid_scroll.geometry())

        self._run_job(PAGE_JOB, job, done)

    def _show_message(self, text: str, *, error: bool = False) -> None:
        self.message.setText(text)
        role = "modal-error" if error else None
        if self.message.property("role") != role:
            self.message.setProperty("role", role)
            _repolish(self.message)
        self.message.setVisible(bool(text))

    def _clear_cards(self) -> None:
        self._icon_loader.clear()
        for card in self._cards:
            self.grid.removeWidget(card)
            card.hide()
            card.deleteLater()
        self._cards = []

    def _show_page(self, result: dict) -> None:
        self._clear_cards()
        self._pages = result["pages"]
        self._page = result["page"]
        results = result["results"]
        for i, listing in enumerate(results):
            card = _Card(listing)
            card.opened.connect(self._open_detail)
            card.install.connect(self._install_listing)
            self.grid.addWidget(card, i // COLUMNS, i % COLUMNS)
            self._cards.append(card)
            self._show_icon(card, listing["icon_url"])
        rows = -(-len(results) // COLUMNS)
        for r in range(max(self.grid.rowCount(), rows + 1)):
            self.grid.setRowStretch(r, 0)
        self.grid.setRowStretch(rows, 1)  # cards keep their height; the slack goes below
        self.grid_scroll.verticalScrollBar().setValue(0)
        self._show_message("" if results else ("No mods match." if self._query or self._category else "No mods listed."))
        self._set_pagination(True)
        self._apply_install_state()

    def _set_pagination(self, ready: bool) -> None:
        self.pagination.setVisible(True)
        self.page_label.setText(f"{self._page} / {self._pages}" if ready else "")
        self.pager_box.setVisible(ready)
        self.prev_button.setEnabled(ready and self._page > 1)
        self.next_button.setEnabled(ready and self._page < self._pages)

    # ---- icons ----
    def _show_icon(self, target, url: str) -> None:
        """Sets the icon if it's cached, else queues the fetch (the
        placeholder stays meanwhile). `target`: a _Card, or a (QLabel,
        size) pair."""
        if not url:
            self._apply_icon(target, None)
            return
        pixmap = self._icons.get(url)
        if pixmap is not None:
            self._apply_icon(target, pixmap)
        else:
            self._icon_loader.request(url)

    @staticmethod
    def _apply_icon(target, pixmap: QPixmap | None) -> None:
        if isinstance(target, _Card):
            target.set_icon(pixmap)
            return
        label, size = target
        if size is None:  # the detail header's ThumbFrame (3.3): the raw icon, shrunk into its box
            label.set_image(pixmap if pixmap is not None and not pixmap.isNull() else None, DETAIL_ICON_PX, DETAIL_ICON_PX)
            return
        if pixmap is None or pixmap.isNull():
            label.clear()
        else:
            label.setPixmap(rounded_pixmap(pixmap, size))

    def _on_icon(self, url: str, data: bytes) -> None:
        if self._closed:
            return
        pixmap = QPixmap()
        if data:
            pixmap.loadFromData(data)
        self._icons[url] = pixmap
        for card in self._cards:
            if card.listing["icon_url"] == url:
                self._apply_icon(card, pixmap)
        if self._detail_listing and self._detail_listing["icon_url"] == url:
            self._apply_icon((self.detail_icon, None), pixmap)
        for icon_url, label in self._dep_icons:
            if icon_url == url:
                self._apply_icon((label, DEP_ICON_PX), pixmap)

    # ---- install ----
    def _install_state(self, full_name: str) -> tuple[str, bool]:
        """(button text, enabled) for a package's Install button."""
        if full_name in self._installed() or full_name == self._framework:
            return "Installed", False
        if self._installing == full_name:
            return "Installing...", False
        return "Install", self._installing is None and not self._is_busy()

    def _installed_version(self, full_name: str) -> str | None:
        """The version the open load order has of a package, or None."""
        entry = self._installed().get(full_name)
        return (entry or {}).get("version") if entry else None

    def _apply_install_state(self) -> None:
        for card in self._cards:
            card.set_install_state(*self._install_state(card.listing["full_name"]))
        self._apply_detail_button()
        if self._detail_listing is not None:
            full = self._detail_listing["full_name"]
            have = self._installed_version(full)
            idle = self._installing is None and not self._is_busy()
            for version, button in self._version_buttons:
                if have is not None and version == have:
                    button.setText("Installed")  # the one this load order has
                    button.setEnabled(False)
                    set_installed_look(button, True)
                elif self._installing == full and version == self._installing_version:
                    button.setText("Installing..." if have is None else "Switching...")
                    set_installed_look(button, False)
                    button.setEnabled(False)
                else:
                    button.setText(f"Install {version}")
                    set_installed_look(button, False)
                    button.setEnabled(idle)

    def _install_listing(self, listing: dict) -> None:
        self._start_install(ts.PackageRef(listing["namespace"], listing["name"]), listing["name"])

    def _install_from_detail(self) -> None:
        """The big button: the selected version for a package the load order
        doesn't have; for one it has at an older version, the update to the
        latest (the button said so)."""
        listing = self._detail_listing
        if listing is None:
            return
        if self._installed_version(listing["full_name"]) is not None:
            self._start_switch(listing["full_name"], None)
            return
        version = self._version if self._version and self._version != self._latest_version() else None
        self._start_install(ts.PackageRef(listing["namespace"], listing["name"], version), listing["name"])

    def _install_version(self, version: str) -> None:
        """A Versions row's Install: that exact version - installed pinned
        when the load order doesn't have the mod, else switched to in
        place (newer or older); the header's selector isn't touched."""
        listing = self._detail_listing
        if listing is None:
            return
        if self._installed_version(listing["full_name"]) is not None:
            self._start_switch(listing["full_name"], version)
            return
        pinned = version if version != self._latest_version() else None
        self._start_install(ts.PackageRef(listing["namespace"], listing["name"], pinned), listing["name"])

    def _start_switch(self, full_name: str, version: str | None) -> None:
        have = self._installed_version(full_name)
        if have is None or self._installing is not None or self._is_busy() or (version or self._latest_version()) == have:
            log(f"browse: switch {full_name} -> {version or 'latest'} ignored")
            return
        self._installing, self._installing_version = full_name, version
        log(f"browse: switch {full_name} {have} -> {version or 'latest'} in {self.load_order_name!r}")
        self._apply_install_state()

        def done(payload: dict) -> None:
            if self._closed:
                return
            self._installing, self._installing_version = None, None
            self._apply_install_state()
            if self._detail_listing and self._detail_listing["full_name"] == full_name:
                self._refresh_chain()

        self._switch_version(full_name, version, done, self)

    def _start_install(self, ref: ts.PackageRef, display_name: str) -> None:
        text, enabled = self._install_state(ref.full_name)
        if not enabled:
            log(f"browse: install {ref.full_name} ignored ({text})")
            return
        self._installing, self._installing_version = ref.full_name, ref.version
        log(f"browse: install {ref.key if ref.version else ref.full_name} into {self.load_order_name!r}")
        self._apply_install_state()

        def done(payload: dict) -> None:
            if self._closed:
                return
            self._installing, self._installing_version = None, None
            if "ok" in payload:
                res = payload["ok"]
                extra = len(res.get("installed", ())) - 1
                log(f"browse: installed {ref.full_name} (+{max(0, extra)} dependencies)")
            self._apply_install_state()
            if self._detail_listing and self._detail_listing["full_name"] == ref.full_name:
                self._refresh_chain()  # the dependencies just landed: the block turns to "already installed"

        self._install(ref, done, self)

    # ---- the detail page ----
    def _latest_version(self) -> str | None:
        return self._detail["latest_version"] if self._detail else (self._versions[0]["version"] if self._versions else None)

    def _open_detail(self, listing: dict, *, keep_tab: bool = False) -> None:
        """A card click: the header from the listing at once, then one job
        for everything else (_run_detail_job); the tab body shows Loading.
        `keep_tab` (Retry): stay on the tab the user picked."""
        self._detail_listing = listing
        self._detail = None
        self._versions = []
        self._version = None
        self._version_meta = None
        self._chain = None
        self._chain_error = None
        self._has_changelog = False
        self._detail_gen += 1
        gen = self._detail_gen
        log(f"browse: detail {listing['full_name']}")
        self.detail_name.set_text(listing["name"])
        self.detail_deprecated.setVisible(bool(listing.get("is_deprecated")))
        self.detail_description.setText(listing["description"] or "")
        self._set_links(listing["namespace"], "")
        # a Required row's listing has no numbers yet (_open_dependency): blank until the job fills them
        self.detail_stats.setText(stats_text(listing["download_count"], listing["rating_count"], listing["size"])
                                  if "download_count" in listing else "")
        self.detail_icon.set_image(None, DETAIL_ICON_PX, DETAIL_ICON_PX)
        self._show_icon((self.detail_icon, None), listing["icon_url"])
        self._set_version_combo(None, "Version: loading...")
        self._set_facts(None)
        self.package_name_edit.setText(listing["full_name"])
        self.package_name_edit.setCursorPosition(0)  # show the Team- start, not the scrolled-to end (a long name)
        self._set_chips([])
        self._clear_tabs()
        self._select_tab(self._tab if keep_tab else "details")
        self._show_status("Loading...", error=False)
        self._apply_detail_button()
        self._switch(1)
        self.back_button.setFocus()
        self._run_detail_job(gen, listing, version=None)

    def _retry_detail(self) -> None:
        if self._detail_listing is not None:
            log(f"browse: retry {self._detail_listing['full_name']}")
            self._open_detail(self._detail_listing, keep_tab=True)

    def _open_dependency(self, dep: dict) -> None:
        """A Required row: that package's page in place (its latest version,
        like a card), the page being left pushed on _history for Back."""
        if self._detail_listing is not None:
            self._history.append((self._detail_listing, self._tab))
        log(f"browse: Required row -> {dep['full_name']} ({len(self._history)} back)")
        self._open_detail({"namespace": dep["namespace"], "name": dep["name"], "full_name": dep["full_name"],
                           "description": dep["description"], "icon_url": dep["icon_url"], "is_deprecated": False})

    def _go_back(self) -> None:
        """Back / Esc / Backspace on the detail page: the previous package's
        page (on the tab it was on) while _history has one, else the results."""
        if not self._history:
            self._show_browse()
            return
        listing, self._tab = self._history.pop()
        log(f"browse: back to {listing['full_name']} ({len(self._history)} back)")
        self._open_detail(listing, keep_tab=True)

    def _run_detail_job(self, gen: int, listing: dict, *, version: str | None) -> None:
        """The detail job. version=None: the whole page (listing detail,
        versions, wiki index, the latest version's pieces); a version: just
        that version's metadata, README and changelog. Text only - the
        images and the dependency chain are background steps started once
        the page shows (_show_detail)."""
        community, app_version = self.game.community, self.app_version
        ns, name = listing["namespace"], listing["name"]
        has_changelog = self._has_changelog

        def job(report):
            out: dict = {}
            if version is None:
                detail = tb.fetch_listing_detail(community, ns, name, app_version)
                versions = tb.fetch_versions(ns, name, app_version)
                if not any(v["version"] == detail["latest_version"] for v in versions):
                    versions.insert(0, {"version": detail["latest_version"], "created": detail["last_updated"], "downloads": 0})
                try:  # package-level, fetched once per page open; its failure only hides the tab
                    wiki = tb.order_wiki_pages(tb.fetch_wiki_index(ns, name, app_version))
                except ts.ThunderstoreError as err:
                    log(f"browse: wiki unavailable for {ns}-{name}: {err}")
                    wiki = []
                out.update(detail=detail, versions=versions, wiki=wiki)
                picked, changelog_wanted = detail["latest_version"], detail["has_changelog"]
            else:
                picked, changelog_wanted = version, has_changelog
            meta = tb.fetch_version(ns, name, picked, app_version)
            try:
                readme = tb.fetch_readme(ns, name, picked, app_version)
            except ts.ThunderstoreError as err:
                log(f"browse: README unavailable for {ns}-{name} {picked}: {err}")
                readme = ""
            changelog = ""
            if changelog_wanted:
                try:
                    changelog = tb.fetch_changelog(ns, name, picked, app_version)
                except ts.ThunderstoreError as err:
                    log(f"browse: changelog unavailable for {ns}-{name} {picked}: {err}")
            out.update(version=picked, meta=meta, readme=readme, changelog=changelog)
            return out

        def done(payload: dict) -> None:
            if self._closed or gen != self._detail_gen:
                return
            if "error" in payload:
                self._show_status(payload["error"], error=True)
                if self._detail is None:
                    self._set_version_combo(None, "Version: unavailable")
                self._apply_detail_button()
                return
            if self.stack.currentIndex() == 1:  # the content replaces "Loading..." under a MOTION_FAST crossfade
                painters.crossfade(self.stack, lambda: self._show_detail(payload["ok"]), theme.MOTION_FAST)
            else:
                self._show_detail(payload["ok"])

        self._run_job(f"browse-detail-{ns}-{name}" + (f"-{version}" if version else ""), job, done)

    def _show_detail(self, res: dict) -> None:
        listing = self._detail_listing
        if "detail" in res:  # the package-level pieces: right column, header, versions
            self._detail = res["detail"]
            self._versions = res["versions"]
            self._has_changelog = self._detail["has_changelog"]
            d = self._detail
            self.detail_deprecated.setVisible(bool(d.get("is_deprecated") or listing.get("is_deprecated")))
            self.detail_description.setText(d["description"] or listing["description"] or "")
            self.detail_stats.setText(stats_text(d["download_count"], d["rating_count"], d["size"]))
            if d["icon_url"] and d["icon_url"] != listing["icon_url"]:
                listing["icon_url"] = d["icon_url"]
                self._show_icon((self.detail_icon, None), listing["icon_url"])
            self._set_version_combo(self._versions, None)
            self._set_facts(d)
            self.package_name_edit.setText(d["full_version_name"])
            self.package_name_edit.setCursorPosition(0)  # show the Team- start, not the scrolled-to end (a long name)
            self._set_chips(d["categories"])
            self._fill_versions_tab()
            self.tab_buttons["changelog"].setVisible(self._has_changelog)
            self._set_wiki(res["wiki"])
        self._version = res["version"]
        self._version_meta = res["meta"]
        website = (self._detail["website_url"] if self._detail else "") or res["meta"]["website_url"]
        self._set_links(listing["namespace"], website)
        self.readme.set_markdown(res["readme"], None, fallback=res["meta"]["description"] or listing["description"])
        if self._has_changelog:
            self.changelog.set_markdown(res["changelog"], None, fallback="No changelog for this version.")
        self._chain_error = None
        self._set_deps(None)  # "checking required mods...", the Required pills Checking..., Install disabled
        self._fill_required_tab()
        hidden = (self._tab == "changelog" and not self._has_changelog) or (self._tab == "wiki" and not self._wiki)
        self._select_tab("details" if hidden else self._tab)  # off the status page
        self._apply_detail_button()
        self._start_chain()
        self._start_images("detail", [res["readme"], res["changelog"] if self._has_changelog else ""])

    def _start_chain(self) -> None:
        """The selected version's dependency chain as a background step
        (parallel_dependency_chain over `_pkg_cache`); when it lands - still
        on this page and version - the block, the Required pills and the big
        button fill in (_refresh_chain re-derives against the load order as
        it is by then). A failure shows in the block; the button stays off."""
        listing, version, gen = self._detail_listing, self._version, self._detail_gen
        deps = list((self._version_meta or {}).get("dependencies") or [])
        installed, framework = set(self._installed()), self._framework
        app_version, cache = self.app_version, self._pkg_cache
        started = time.monotonic()

        def job(report):
            return tb.parallel_dependency_chain(deps, installed, framework, app_version, cache=cache)

        def done(payload: dict) -> None:
            if self._closed or gen != self._detail_gen:
                log(f"browse: dependency chain for {listing['full_name']} {version} dropped (page left)")
                return
            if "error" in payload:
                log(f"browse: dependency chain for {listing['full_name']} {version} failed: {clip(payload['error'])}")
                self._chain_error = payload["error"]
                self._set_deps(None)
                self._fill_required_tab()
                self._apply_detail_button()
                return
            chain = payload["ok"]
            log(f"browse: dependency chain for {listing['full_name']} {version} in {time.monotonic() - started:.2f}s: "
                f"{len(chain['satisfied'])} installed, {len(chain['missing'])} to install, {len(chain['problems'])} problems")
            self._chain = chain
            self._refresh_chain()

        log(f"browse: dependency chain for {listing['full_name']} {version}: {len(deps)} declared, "
            f"{len(cache)} packages in the window's cache")
        self._run_job(f"browse-chain-{listing['full_name']}-{version}", job, done)

    def _start_images(self, target: str, markdowns: list[str]) -> None:
        """The images of a page as a background step (thunderstore_browse.
        load_images): target "detail" = the README's then the changelog's
        (the queue's order is the priority), else a wiki page id. Each one
        reaches _on_image as it lands; a newer page / version / wiki page or
        the window closing (the generation moved on) abandons the queue."""
        urls: list[str] = []
        for markdown in markdowns:
            urls += [u for u in tb.image_urls(markdown) if u not in urls]
        have = self.wiki_readme.images if target != "detail" else {}
        urls = [u for u in urls if u not in have]  # a cached wiki page shown again: only what it's missing
        if not urls:
            return
        wiki = target != "detail"
        gen = self._wiki_gen if wiki else self._detail_gen
        feed, app_version, app_root = self._image_feed, self.app_version, self._app_root

        def superseded() -> bool:
            return self._closed or gen != (self._wiki_gen if wiki else self._detail_gen)

        def job(report):
            return tb.load_images(urls, app_version, app_root=app_root, shrink=shrink_image, cancelled=superseded,
                                  on_image=lambda url, data: feed.arrived.emit((target, gen, url, data)))

        self._run_job(f"browse-images-{target}-{gen}", job, lambda payload: None)

    def _on_image(self, payload) -> None:
        """An image from a background step (GUI thread): into the page's
        _Readme(s) while that page is still the one showing; a wiki page's
        also into its cache entry, for its next showing."""
        target, gen, url, data = payload
        if self._closed:
            return
        if target == "detail":
            if gen == self._detail_gen:
                self.readme.add_images({url: data})
                self.changelog.add_images({url: data})
            return
        page = self._wiki_pages.get(target)
        if page is not None:
            page["images"][url] = data
        if gen == self._wiki_gen:
            self.wiki_readme.add_images({url: data})

    def _version_changed(self) -> None:
        version = self.version_combo.currentData()
        listing = self._detail_listing
        if not version or listing is None or version == self._version:
            return
        self._version = version
        self._detail_gen += 1
        gen = self._detail_gen
        log(f"browse: {listing['full_name']} version {version} picked")
        self._chain = None
        self._version_meta = None  # the tabs hold the previous version until the job lands
        self._show_status("Loading...", error=False)
        self._apply_detail_button()
        self._run_detail_job(gen, listing, version=version)

    def _refresh_chain(self) -> None:
        """After an install from the detail page: re-derive the block from
        the load order's new contents, no network (everything that was
        missing is installed now, or reported by the screen)."""
        chain = self._chain
        if chain is None:
            return
        installed = set(self._installed())
        satisfied = chain["satisfied"] + [n for n in chain["missing"] if n in installed]
        missing = [n for n in chain["missing"] if n not in installed]
        self._set_deps({"satisfied": satisfied, "missing": missing, "problems": chain["problems"]})
        self._fill_required_tab()
        self._apply_detail_button()

    # ---- detail: the pieces ----
    def _set_links(self, namespace: str, website: str) -> None:
        # the drawn people / link icons (icons.py; were the 👥 / 🔗 emoji), link-blue like the text
        parts = [link_html(tb.team_page_url(self.game.community, namespace),
                           f"{icons.inline('people', theme.ACCENT)} {namespace}")]
        if website:
            parts.append(link_html(website, f"{icons.inline('link', theme.ACCENT)} {shown_url(website)}"))
        self.detail_links.setText("&nbsp;&nbsp;&nbsp;&nbsp;".join(parts))

    def _set_version_combo(self, versions: list[dict] | None, placeholder: str | None) -> None:
        combo = self.version_combo
        combo.blockSignals(True)
        combo.clear()
        if versions:
            latest = self._latest_version()
            for v in versions:
                combo.addItem(f"Version: {v['version']}" + (" (latest)" if v["version"] == latest else ""), v["version"])
            combo.setCurrentIndex(0)
            combo.setEnabled(len(versions) > 1)
        else:
            combo.addItem(placeholder or "Version: -")
            combo.setEnabled(False)
        combo.blockSignals(False)

    def _set_facts(self, d: dict | None) -> None:
        f = self.fact_values
        if d is None:
            for value in f.values():
                value.setText("-")
            return
        f["latest"].setText(d["latest_version"])
        f["updated"].setText(age_html(d["last_updated"]))
        f["uploaded"].setText(date_text(d["first_uploaded"]))
        f["downloads"].setText(tb.format_count(d["download_count"]))
        f["likes"].setText(tb.format_count(d["rating_count"]))
        f["size"].setText(tb.format_size(d["size"]) if d["size"] else "-")
        count = d["dependant_count"]
        f["dependants"].setText(link_html(tb.dependants_page_url(self.game.community, d["namespace"], d["name"]),
                                          f"{tb.format_count(count)} other mod{'s' if count != 1 else ''}"))
        f["dependants"].setToolTip("Opens the list of mods that need this one, on thunderstore.io")

    def _set_chips(self, categories: list[dict]) -> None:
        _clear_layout(self.chips_layout)
        for c in categories:
            chip = QPushButton(c["name"])
            chip.setProperty("variant", "browse-chip")
            chip.setAutoDefault(False)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(f"Show the results filtered by {c['name']}")
            chip.clicked.connect(lambda _=False, cid=c["id"], cname=c["name"]: self._filter_by_category(cid, cname))
            self.chips_layout.addWidget(chip)

    def _filter_by_category(self, category_id: str, name: str) -> None:
        """A category chip: back to the results, filtered by that category
        (the combo's entry, when the category list loaded)."""
        index = self.category_combo.findData(category_id)
        log(f"browse: category chip {name!r} ({category_id}) -> results{'' if index >= 0 else ' (category not in the list)'}")
        self._show_browse()
        if index >= 0 and index != self.category_combo.currentIndex():
            self.category_combo.setCurrentIndex(index)  # -> _filters_changed -> page 1

    def _copy_package_name(self) -> None:
        text = self.package_name_edit.text()
        if text:
            QGuiApplication.clipboard().setText(text)
            log(f"browse: copied {text!r}")

    def _select_tab(self, key: str, *, animate: bool = False) -> None:
        """animate (a tab clicked): the underline slides and the page
        crossfades (MOTION_FAST); a programmatic switch (a new mod, a load)
        snaps both."""
        self._tab = key
        for k, button in self.tab_buttons.items():
            selected = k == key
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                _repolish(button)
        self.tab_indicator.moved(animate)
        if self._version_meta is not None:  # loaded: show the tab; loading / error keep the status page
            index = TAB_INDEX[key]
            if animate and index != self.tab_stack.currentIndex():
                painters.crossfade(self.tab_stack, lambda: self.tab_stack.setCurrentIndex(index), theme.MOTION_FAST)
            else:
                self.tab_stack.setCurrentIndex(index)
            if key == "wiki" and self._wiki_page is None and self._wiki:
                self._select_wiki_page(self._wiki[0]["id"])  # lazy: the first page on the tab's first opening

    def _show_status(self, text: str, *, error: bool) -> None:
        _set_status(self.detail_message, self.retry_button, text, error)
        self.tab_stack.setCurrentIndex(0)

    # ---- the Wiki tab ----
    def _set_wiki(self, pages: list[dict]) -> None:
        """A package's wiki index (rail order): the rail's entries and the tab
        button ("Wiki (N)", hidden with no pages). Resets the page state."""
        self._wiki = pages
        self._wiki_pages = {}
        self._wiki_page = None
        self._wiki_gen += 1  # a page reply for the previous package is dropped
        _clear_layout(self.wiki_rail)
        self._wiki_buttons = {}
        for page in pages:
            button = QPushButton()
            button.setProperty("variant", "help-entry")
            button.setAutoDefault(False)
            button.setText(button.fontMetrics().elidedText(page["title"], Qt.TextElideMode.ElideRight, WIKI_RAIL_WIDTH - WIKI_ENTRY_ROOM))
            button.setToolTip(page["title"])
            button.clicked.connect(lambda _=False, page_id=page["id"]: self._select_wiki_page(page_id))
            self.wiki_rail.addWidget(button)
            self._wiki_buttons[page["id"]] = button
        self.wiki_rail.addStretch(1)
        self.tab_buttons["wiki"].setText(f"Wiki ({len(pages)})" if pages else "Wiki")
        self.tab_buttons["wiki"].setVisible(bool(pages))

    def _select_wiki_page(self, page_id: str) -> None:
        """A rail entry (or the tab's first opening): the page from this
        package's cache, else one job for its markdown + images."""
        self._wiki_page = page_id
        self._wiki_gen += 1  # a reply for the page picked before is dropped
        gen = self._wiki_gen
        for key, button in self._wiki_buttons.items():
            if button.property("selected") != (key == page_id):
                button.setProperty("selected", key == page_id)
                _repolish(button)
        cached = self._wiki_pages.get(page_id)
        if cached is not None:
            self._show_wiki_page(cached)
            return
        app_version = self.app_version
        title = next((p["title"] for p in self._wiki if p["id"] == page_id), "?")
        log(f"browse: wiki page {page_id} ({clip(title)}) of {self._detail_listing['full_name'] if self._detail_listing else '?'}")
        _set_status(self.wiki_message, self.wiki_retry, "Loading...", False)
        self.wiki_stack.setCurrentIndex(0)

        def job(report):
            return {"markdown": tb.fetch_wiki_page(page_id, app_version), "images": {}}  # images: _start_images

        def done(payload: dict) -> None:
            if self._closed or gen != self._wiki_gen:
                return
            if "error" in payload:
                log(f"browse: wiki page {page_id} failed: {clip(payload['error'])}")
                _set_status(self.wiki_message, self.wiki_retry, payload["error"], True)
                return
            self._wiki_pages[page_id] = payload["ok"]
            # the page replaces "Loading..." under a MOTION_FAST crossfade, as the README does
            painters.crossfade(self.wiki_stack, lambda: self._show_wiki_page(payload["ok"]), theme.MOTION_FAST)

        self._run_job(f"browse-wiki-{page_id}", job, done)

    def _show_wiki_page(self, page: dict) -> None:
        self.wiki_readme.set_markdown(page["markdown"], page["images"], fallback="This wiki page is empty.")
        self.wiki_stack.setCurrentIndex(1)
        if self._wiki_page is not None:
            self._start_images(self._wiki_page, [page["markdown"]])

    def _retry_wiki(self) -> None:
        if self._wiki_page is not None:
            log(f"browse: wiki retry {self._wiki_page}")
            self._select_wiki_page(self._wiki_page)

    def _clear_tabs(self) -> None:
        self._version_meta = None
        self.readme.set_markdown("", fallback="")
        self.changelog.set_markdown("", fallback="")
        self._set_deps(None)
        _clear_layout(self.required_layout)
        _clear_layout(self.versions_layout)
        self._version_buttons = []
        self._dep_icons = []
        self.tab_buttons["required"].setText("Required")
        self.tab_buttons["changelog"].setVisible(True)
        self._set_wiki([])  # hidden until the package's index says it has pages

    def _set_deps(self, chain: dict | None) -> None:
        """The Details tab's dependency block (0.6.31: a summary - a modpack's
        41 rows, one per dependency, grew the window and squeezed the README):
        one line of counts with a "See the Required tab" link, then only the
        dependencies with a problem (⚠, warn), at most DEPS_PROBLEMS_SHOWN,
        then "and N more"; past CHAIN_LIMIT a muted note says the rest
        aren't counted (that marker is not a problem and not in the total).
        None: the chain step is still running (or failed: _chain_error)."""
        self._chain = chain
        _clear_layout(self.deps_layout)
        if chain is None:
            self.deps_label.setText(f"couldn't check required mods: {self._chain_error}" if self._chain_error
                                    else "checking required mods...")
            return
        satisfied, missing = len(chain["satisfied"]), len(chain["missing"])
        problems = [p for p in chain["problems"] if p[1] != tb.CHAIN_LIMIT_MESSAGE]
        cut_off = len(problems) != len(chain["problems"])  # the CHAIN_LIMIT marker: its own note, not counted
        total = satisfied + missing + len(problems)
        if not total and not cut_off:
            self.deps_label.setText("nothing else - it needs no other mods.")
            return
        self.deps_label.setText("installed automatically with this mod")
        counts = [f"{satisfied} already installed", f"{missing} will be installed"]
        if problems:
            counts.append(f"{len(problems)} {'has a problem' if len(problems) == 1 else 'have problems'}")
        summary = QLabel(f"{total} required mod{'s' if total != 1 else ''}: {', '.join(counts)}."
                         f"&nbsp;&nbsp;{link_html('#required', 'See the Required tab')}")
        summary.setTextFormat(Qt.TextFormat.RichText)
        summary.setWordWrap(True)
        summary.linkActivated.connect(lambda _href: self._select_tab("required", animate=True))
        self.deps_layout.addWidget(summary)
        # the problem rows: the old block's ⚠ rows (a drawn icon in the row's --warn)
        for name, text in problems[:DEPS_PROBLEMS_SHOWN]:
            label = QLabel(f"{icons.inline('warn', theme.WARN)} "
                           f'<span style="font-family: {MONO_HTML}; font-size: 12px">{html.escape(name)}</span> '
                           f'<span style="color: {theme.MUTED}">— {html.escape(text)}</span>')
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(True)
            label.setProperty("role", "browse-dep-problem")
            self.deps_layout.addWidget(label)
        if len(problems) > DEPS_PROBLEMS_SHOWN:
            more = QLabel(f"and {len(problems) - DEPS_PROBLEMS_SHOWN} more")
            more.setProperty("muted", True)
            self.deps_layout.addWidget(more)
        if cut_off:
            note = QLabel(f"It needs more than {tb.CHAIN_LIMIT} required mods; the rest aren't counted here.")
            note.setProperty("muted", True)
            note.setWordWrap(True)
            self.deps_layout.addWidget(note)

    def _dep_status(self, full_name: str) -> tuple[str, str]:
        """(pill text, pill state) of a dependency for the Required tab;
        "pending" (a plain muted pill) while the chain step runs."""
        chain = self._chain or {"satisfied": [], "missing": [], "problems": []}
        if full_name in chain["satisfied"] or full_name in self._installed() or full_name == self._framework:
            return "Already installed", "ok"
        if self._chain is None:
            return ("Couldn't check", "warn") if self._chain_error else ("Checking...", "pending")
        if any(n == full_name for n, _ in chain["problems"]):
            return "Unavailable", "warn"
        return "Will be installed", "get"

    def _fill_required_tab(self) -> None:
        """The selected version's direct dependencies as rich rows: icon,
        name, team, description, the declared version, a status pill. The
        listing detail's rows (latest) carry descriptions and icons; an
        older version's list (fetch_version's strings) has only names."""
        _clear_layout(self.required_layout)
        self._dep_icons = []
        rows: list[dict] = []
        detail_deps = {d["full_name"]: d for d in (self._detail["dependencies"] if self._detail else [])}
        for dep in (self._version_meta or {}).get("dependencies", []):
            try:
                ref = ts.PackageRef.parse(dep)
            except ValueError:
                continue
            known = detail_deps.get(ref.full_name, {})
            rows.append({"full_name": ref.full_name, "namespace": ref.namespace, "name": ref.name, "version": ref.version or "",
                         "description": known.get("description", ""), "icon_url": known.get("icon_url", "")})
        self.tab_buttons["required"].setText(f"Required ({len(rows)})")
        if not rows:
            empty = QLabel("This mod needs no other mods.")
            empty.setProperty("muted", True)
            self.required_layout.addWidget(empty)
            self.required_layout.addStretch(1)
            return
        for r in rows:
            row = _DepRow(r)
            row.opened.connect(lambda dep: self._open_dependency(dep))
            layout = QHBoxLayout(row)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(14)
            icon = QLabel()
            icon.setProperty("role", "browse-icon")
            icon.setFixedSize(DEP_ICON_PX, DEP_ICON_PX)
            layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            if r["icon_url"]:
                self._dep_icons.append((r["icon_url"], icon))
                self._show_icon((icon, DEP_ICON_PX), r["icon_url"])
            text = QVBoxLayout()
            text.setSpacing(4)
            name = QLabel(f"<b>{r['name']}</b> <span style='color:{theme.MUTED}'>by {r['namespace']}</span>")
            name.setTextFormat(Qt.TextFormat.RichText)
            text.addWidget(name)
            if r["description"]:
                desc = QLabel(r["description"])
                desc.setProperty("muted", True)
                desc.setTextFormat(Qt.TextFormat.PlainText)
                desc.setWordWrap(True)
                text.addWidget(desc)
            version = QLabel(f"Version: <span style='color:{theme.ACCENT}'>{r['version'] or '?'}</span> (the version it lists; VOLT installs the latest)")
            version.setTextFormat(Qt.TextFormat.RichText)
            version.setProperty("role", "browse-small")
            text.addWidget(version)
            layout.addLayout(text, 1)
            status, state = self._dep_status(r["full_name"])
            pill = QLabel(status)
            pill.setProperty("role", "browse-pill")
            pill.setProperty("state", state)
            pill.setProperty("muted", state == "pending")  # no tint of its own: the existing muted text (0.6.31)
            layout.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
            self.required_layout.addWidget(row)
        self.required_layout.addStretch(1)

    def _fill_versions_tab(self) -> None:
        """Version · upload date · downloads · [Install x.y.z] per version."""
        _clear_layout(self.versions_layout)
        self._version_buttons = []
        head = QFrame()
        head.setProperty("role", "browse-vrow")
        head.setProperty("head", True)
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(10, 6, 10, 6)
        for title, width in (("Version", 150), ("Upload date", 0), ("Downloads", 120), ("", 130)):
            label = QLabel(title)
            label.setProperty("role", "browse-small")
            if width:
                label.setFixedWidth(width)
            head_layout.addWidget(label, 0 if width else 1)
        self.versions_layout.addWidget(head)
        latest = self._latest_version()
        for v in self._versions:
            row = QFrame()
            row.setProperty("role", "browse-vrow")
            layout = QHBoxLayout(row)
            layout.setContentsMargins(10, 6, 10, 6)
            number = QLabel(f"<b>{v['version']}</b>" + (f" <span style='color:{theme.MUTED}'>latest</span>" if v["version"] == latest else ""))
            number.setTextFormat(Qt.TextFormat.RichText)
            number.setFixedWidth(150)
            layout.addWidget(number)
            when = _parse_iso(v["created"])
            date = QLabel(when.strftime("%b %d, %Y, %H:%M") if when else "-")
            date.setProperty("muted", True)
            layout.addWidget(date, 1)
            downloads = QLabel(tb.format_count(v["downloads"]))
            downloads.setProperty("muted", True)
            downloads.setFixedWidth(120)
            layout.addWidget(downloads)
            button = QPushButton(f"Install {v['version']}")
            button.setProperty("variant", "accent-outline")
            button.setAutoDefault(False)
            button.setFixedWidth(130)
            button.clicked.connect(lambda _=False, ver=v["version"]: self._install_version(ver))
            layout.addWidget(button)
            self.versions_layout.addWidget(row)
            self._version_buttons.append((v["version"], button))
        self.versions_layout.addStretch(1)
        self._apply_install_state()

    def _apply_detail_button(self) -> None:
        """The big button: Install <name> (+ N deps) to <lo> for a mod the
        load order doesn't have (the selected version); for one it has:
        "already in" at the latest, else "Update <name> to <latest>";
        Installing... / Updating... while a job runs. The text is fitted
        to the button (fit_button_text), never clipped."""
        listing = self._detail_listing
        button = self.detail_install_button
        if listing is None:
            set_installed_look(button, False)
            self._set_button_text(button, "Install")
            button.setEnabled(False)
            return
        full, name, lo = listing["full_name"], listing["name"], self.load_order_name
        have = self._installed_version(full)
        latest = self._latest_version()
        idle = self._installing is None and not self._is_busy()
        installed = False
        if self._installing == full:
            text, enabled = f"{'Updating' if have is not None else 'Installing'} {name}...", False
        elif full == self._framework or (have is not None and (not latest or not ts.is_newer(latest, have))):
            text, enabled = f"{name} is already in {lo}", False
            installed = True
        elif have is not None:
            text, enabled = f"Update {name} to {latest} in {lo}", idle
        elif self._chain is None:
            text, enabled = install_label(name, 0, lo), False  # until the dependency chain is known
        else:
            text, enabled = install_label(name, len(self._chain["missing"]), lo), idle
        set_installed_look(button, installed)  # before the fit: the check + bold take room
        self._set_button_text(button, text, reserve=INSTALLED_ICON_ROOM if installed else 0)
        button.setEnabled(enabled)

    @staticmethod
    def _set_button_text(button: QPushButton, text: str, reserve: int = 0) -> None:
        width = button.width() if button.width() > 50 else RIGHT_COLUMN_WIDTH
        label, changed = fit_button_text(text, button.fontMetrics(), width - BUTTON_TEXT_PADDING - reserve)
        button.setText(label)
        button.setToolTip(text if changed else "")

    # ---- pages ----
    def _show_browse(self) -> None:
        self._detail_gen += 1  # a detail reply arriving now is dropped
        self._detail_listing = None
        self._history.clear()
        self._switch(0)
        self._apply_install_state()
        self.grid_scroll.setFocus()  # not the search box: Esc closes / Backspace idles from here

    def eventFilter(self, obj, event) -> bool:
        """The filter strip's focus edge (3.2): lit while the search box or a
        combo has focus - kept while a combo's own drop-down is open (that
        focus-out has the Popup reason and the combo gets focus back)."""
        kind = event.type()
        if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            if not (kind == QEvent.Type.FocusOut and event.reason() == Qt.FocusReason.PopupFocusReason):
                on = kind == QEvent.Type.FocusIn
                if self.filter_strip.property("fieldFocus") != on:
                    self.filter_strip.setProperty("fieldFocus", on)
                    _repolish(self.filter_strip)
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        """Esc / Backspace: one level back (module docstring)."""
        key = event.key()
        on_detail = self.stack.currentIndex() == 1
        if key == Qt.Key.Key_Escape:
            if on_detail:
                log("browse: Esc -> one level back")
                self._go_back()
                event.accept()
                return
            if self.search.hasFocus() and self.search.text():
                self.search.clear()  # the Edit Config window's rule: Esc clears a query first
                event.accept()
                return
            super().keyPressEvent(event)  # QDialog: reject
            return
        if key == Qt.Key.Key_Backspace:
            if isinstance(self.focusWidget(), (QLineEdit, QTextEdit)):
                super().keyPressEvent(event)  # a text field's own Backspace (it normally never reaches here)
                return
            if on_detail:
                log("browse: Backspace -> one level back")
                self._go_back()
            event.accept()
            return
        super().keyPressEvent(event)

    def _switch(self, index: int) -> None:
        """Shows a page under a MOTION crossfade (SCOPE.md §2: no instant
        cuts; phase 4 M1 - a snapshot of the page leaving fades out over the
        page arriving, which gets no effect). Detail -> detail (a Required
        row, Back to the previous package, Retry: _open_detail while the
        detail page shows): the page is already refilled, so it fades in from
        the window's --panel instead; the content then crossfades over
        "Loading..." when the job lands (_run_detail_job, which ends this
        fade first - painters.stop_fades)."""
        if index == self.stack.currentIndex():
            painters.fade_in(self.stack, theme.PANEL, theme.MOTION)
            return
        painters.crossfade(self.stack, lambda: self.stack.setCurrentIndex(index), theme.MOTION)

    # ---- lifecycle ----
    def done(self, result: int) -> None:
        self._closed = True
        self._icon_loader.stop()
        log(f"browse window closed ({len(self._page_cache)} pages viewed)")
        super().done(result)
        self.deleteLater()  # not kept around by the screen like the smaller modals: the page / icon caches die with it
