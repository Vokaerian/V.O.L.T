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

  Browse   Browse Thunderstore Mods                                    [✕]
           [Search mods...             ] [Category: All v] [Sort: v]
           4-column card grid (icon, name, "by author", description,
           "⬇ downloads", Install), the cards sharing the grid's whole
           width; 16 per page = 4 rows, every page full (the pinned
           packages the site puts first are taken out and the page topped
           up from the next site page - PagedListing), the grid scrolls
                      ‹ Prev   Page 1 of 337   Next ›
  Detail   [← Back to results]                                         [✕]
           ┌ header card ─────────────────────────────┐ ┌ right column ─┐
           │ icon │ Name (22px)         [Version: v]  │ │ [Install X + N │
           │      │ short description                │ │  deps to <lo>] │
           │      │ 👥 author (site)  🔗 website      │ │ [Team-Pkg-ver ⧉]│
           │      │ ⬇ downloads · ★ ratings · size   │ │ Latest version │
           └──────────────────────────────────────────┘ │ Last updated  │
           [Details] [Required (N)] [Versions] [Changelog]│ First uploaded│
           ┌ tab body ────────────────────────────────┐ │ Downloads     │
           │ Details: the README (images included),   │ │ Likes / Size  │
           │   the ✓/↓/⚠ dependency block under it    │ │ Dependants ↗  │
           │ Required: one rich row per dependency    │ │ Categories    │
           │ Versions: version · date · downloads ·   │ │  [chip] [chip]│
           │   [Install x.y.z] / Installed on the     │ └───────────────┘
           │   version this load order has            │
           │ Changelog: the version's changelog       │
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
<div> or a bare <img>. Images (prefetched on the job thread) are served
through loadResource scaled to the README box's width (never upscaled,
tall ones capped), and refitted on a resize.

Data (volt_py/thunderstore_browse.py): every search / sort / category
change and page turn is one or two small requests to the site's own paged
listing (Option B; a PagedListing per search keeps the site pages it
fetched) - nothing is fetched until it's asked for, and only what this
window already showed is kept (in memory, dying with the window). Sort
opens on Most downloaded (user, 2026-09-29). Search waits
SEARCH_DEBOUNCE_MS after the last keystroke; a reply for a query that was
superseded meanwhile is dropped (a generation counter). Pinned packages
(the framework pack, r2modman) never appear. Icons load lazily on a small
worker pool (_IconLoader, newest request first, the current page's queue
replacing the last page's) behind the mockup's blank placeholder. A
detail page is one job: the listing detail, the versions list, the
selected version's metadata, README + changelog (their images prefetched
on the same thread, handed to the text browser through loadResource - no
network inside the widget) and the dependency chain; picking another
version is the same job minus the package-level pieces.

Install (a card's button, the right column's big one, or a Versions row)
hands the PackageRef to the manager screen's install callback - the same
job as "Add mod..." (download into the shared cache if absent,
dependencies first, appended to the open load order's Active list, the
screen's lists refreshed) - and the window stays open so the next mod can
follow; the button reads Installing... then Installed. The dependency
block and the Install label come from thunderstore_browse.dependency_chain
over the selected version's declared dependencies against what the load
order already has.

Every request runs on a job thread the screen provides (`run_job`, its
_run_job) so the window never blocks; the screen's own busy lock (one
mutating job at a time) is honored through `is_busy`.

Keys: Esc / Backspace go one level back - from the detail page to the
results (search, page and scroll kept, like "← Back to results"); on the
browse page Esc closes the window, Backspace does nothing. In the search
box (any text field) Backspace edits the text as usual; Esc there clears
a query first (the Edit Config window's rule) and closes only when the
box is empty.
"""

import threading
from datetime import datetime, timezone

import re

from PySide6.QtCore import QObject, QPropertyAnimation, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath, QPixmap, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from volt_py import theme, thunderstore as ts, thunderstore_browse as tb
from volt_py.applog import log
from volt_py.screens.flow_layout import FlowLayout

WINDOW_SIZE = (1400, 820)  # .modal.browse-mods
MODAL_GAP = 12  # .modal gap
COLUMNS = 4  # was the mockup's 5; 4 wider cards per row, sharing the grid's full width (user, 2026-09-29)
CARD_GAP = 12  # .card-grid gap
CARD_HEIGHT = 156  # 4 rows of 4 = a page (thunderstore_browse.PAGE_SIZE); the grid scrolls at the 820px minimum
INITIAL_ORDERING = "most-downloaded"  # the sort the browser opens on (user, 2026-09-29; the mockup said Last updated)
CARD_PADDING = 10
ICON_PX = 40  # .card-icon
DETAIL_ICON_PX = 96  # the header card's icon
DEP_ICON_PX = 56  # a Required row's icon
DESC_LINES = 3  # the card description is clamped to this many lines
SEARCH_DEBOUNCE_MS = 300
FADE_MS = 150  # the browse <-> detail switch (SCOPE.md §2)
ICON_WORKERS = 3
CLOSE_PX = 30  # .close-btn
VERSION_PICKER_WIDTH = 240  # the header's selector
RIGHT_COLUMN_WIDTH = 300  # the facts column (fixed on every window width; the left column flexes)
CHIP_GAP = 6
PAGE_JOB = "browse-list"
TABS = (("details", "Details"), ("required", "Required"), ("versions", "Versions"), ("changelog", "Changelog"))
TAB_INDEX = {"details": 1, "required": 2, "versions": 3, "changelog": 4}  # tab_stack pages; 0 = the status page
IMAGE_MAX_HEIGHT = 1200  # a README image taller than this is scaled down (a whole-page banner never fills the box)
REFIT_MS = 150  # the README re-lays its images out this long after the last resize
AGE_MONTH_DAYS, AGE_YEAR_DAYS = 30, 365  # "Last updated": days -> green, months -> yellow, years -> red
AGE_COLORS = (theme.RDEP, theme.WARN, theme.DANGER)
BUTTON_TEXT_PADDING = 24  # the big Install button's horizontal padding + border, for fitting its text


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
    """The big button: "Install EpicLoot + 1 dependency to Vanilla+"."""
    extra = f" + {missing} dependenc{'ies' if missing != 1 else 'y'}" if missing else ""
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
    it fits `width`; else two lines split at the last " to " (the load
    order on the second), each elided to fit (the name line in the
    middle, so "+ N dependencies" survives; the load order line on the
    right). Returns (label, changed)."""
    if fm.horizontalAdvance(text) <= width:
        return text, False
    head, sep, tail = text.rpartition(" to ")
    lines = [head, f"to {tail}"] if sep else [text]
    fitted = [fm.elidedText(lines[0], Qt.TextElideMode.ElideMiddle, width)]
    if len(lines) > 1:
        fitted.append(fm.elidedText(lines[1], Qt.TextElideMode.ElideRight, width))
    return "\n".join(fitted), True


def render_markdown_html(markdown: str) -> str:
    """The README as one HTML document: split_html_blocks' markdown chunks
    through Qt's markdown importer (a scratch QTextDocument -> toHtml's
    body), its HTML chunks as they are."""
    parts: list[str] = []
    for kind, text in tb.split_html_blocks(markdown):
        if kind == "html":
            parts.append(text)
        elif text.strip():
            doc = QTextDocument()
            doc.setMarkdown(text)
            parts.append(_html_body(doc.toHtml()))
    return "\n".join(parts)


def _html_body(html: str) -> str:
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else html


def stats_text(downloads: int, ratings: int, size: int) -> str:
    """The header's green line: "⬇ 2,254,655  ·  ★ 335 ratings  ·  31.2 MB"."""
    parts = [f"⬇ {tb.format_count(downloads)}", f"★ {tb.format_count(ratings)} rating{'s' if ratings != 1 else ''}"]
    if size:
        parts.append(tb.format_size(size))
    return "  ·  ".join(parts)


def link_html(url: str, text: str) -> str:
    return f'<a href="{url}" style="color:{theme.ACCENT}; text-decoration: none">{text}</a>'


def shown_url(url: str) -> str:
    return url.split("://", 1)[-1].removeprefix("www.").rstrip("/")


def rounded_pixmap(pixmap: QPixmap, size: int, radius: int = theme.RADIUS) -> QPixmap:
    """The icon scaled to size x size with the card's corner radius (the
    mockup's border-radius on the icon placeholders)."""
    scaled = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return out


class _IconLoader(QObject):
    """Fetches icons off the GUI thread: request(url) queues it (newest
    first - the page on screen beats one scrolled past), `loaded` brings
    the bytes back over a queued connection (b"" when the fetch failed)."""

    loaded = Signal(str, object)  # url, bytes

    def __init__(self, app_version) -> None:
        # No Qt parent on purpose: the workers keep this object alive until
        # they finish, so a late reply never lands on a deleted receiver.
        super().__init__()
        self._app_version = app_version
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
                data = tb.fetch_bytes(url, self._app_version)
            except (ts.ThunderstoreError, ValueError) as err:
                log(f"[browse] icon {url}: {err}")
                data = b""
            if not self._stopped:
                try:
                    self.loaded.emit(url, data)
                except RuntimeError:  # the window is gone
                    return


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
        self.setToolTip(self._full)
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
    A click anywhere but the button opens the detail page (`opened`)."""

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
        layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        layout.setSpacing(6)  # .card gap
        head = QHBoxLayout()  # .card-head
        head.setSpacing(8)
        self.icon = QLabel()
        self.icon.setProperty("role", "browse-icon")
        self.icon.setFixedSize(ICON_PX, ICON_PX)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.name = _ElidedLabel("browse-name")
        self.name.set_text(listing["name"])
        self.author = _ElidedLabel("browse-small")
        self.author.set_text(f"by {listing['namespace']}")
        names.addWidget(self.name)
        names.addWidget(self.author)
        names.addStretch(1)
        head.addLayout(names, 1)
        layout.addLayout(head)
        self.description = _ClampedLabel("browse-desc")
        self.description.set_text(listing["description"])
        layout.addWidget(self.description)
        layout.addStretch(1)
        foot = QHBoxLayout()  # .card-foot: space-between
        foot.setSpacing(8)
        self.downloads = QLabel(f"⬇ {tb.format_count(listing['download_count'])}")
        self.downloads.setProperty("role", "browse-small")
        self.downloads.setToolTip("Downloads")
        foot.addWidget(self.downloads)
        foot.addStretch(1)
        self.install_button = QPushButton("Install")
        self.install_button.setProperty("variant", "accent-outline")
        self.install_button.setAutoDefault(False)
        self.install_button.setCursor(Qt.CursorShape.ArrowCursor)
        self.install_button.clicked.connect(lambda _=False: self.install.emit(self.listing))
        foot.addWidget(self.install_button)
        layout.addLayout(foot)

    def set_icon(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.icon.clear()
            return
        self.icon.setPixmap(rounded_pixmap(pixmap, ICON_PX))

    def set_install_state(self, text: str, enabled: bool) -> None:
        self.install_button.setText(text)
        self.install_button.setEnabled(enabled)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.opened.emit(self.listing)


class _Readme(QTextBrowser):
    """The README / changelog box: markdown (+ raw HTML, render_markdown_html),
    external links, and the images the job thread prefetched (`images`:
    url -> bytes) served through loadResource - Qt asks for each image at
    layout time, this answers from memory, never from the network, scaled
    to the box's width (never up; IMAGE_MAX_HEIGHT caps a tall one) and
    re-served after a resize (the document is set again, REFIT_MS after the
    last resize, the scroll position kept). An image that wasn't fetched
    stays a blank box (Qt's default)."""

    def __init__(self, object_name: str) -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.setOpenExternalLinks(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.images: dict[str, bytes] = {}
        self._decoded: dict[str, QImage] = {}  # url -> the native image
        self._html = ""
        self._fit_width = 0  # the width the images were last scaled for
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.setInterval(REFIT_MS)
        self._refit_timer.timeout.connect(lambda: self._refit())

    def set_markdown(self, markdown: str, images: dict[str, bytes] | None = None, *, fallback: str = "") -> None:
        self.images = dict(images or {})
        self._decoded = {}
        self._html = render_markdown_html(markdown) if markdown.strip() else ""
        self._fit_width = self._available_width()
        if self._html:
            self.setHtml(self._html)
        else:
            self.setPlainText(fallback.strip() or "No description.")
        self.verticalScrollBar().setValue(0)

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
        if not self._html or self._available_width() == self._fit_width:
            return
        self._fit_width = self._available_width()
        scroll = self.verticalScrollBar().value()
        self.setHtml(self._html)  # the document's resource cache goes with it: loadResource scales again
        self.verticalScrollBar().setValue(scroll)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _close_button() -> QPushButton:
    button = QPushButton("✕")  # .close-btn 30x30
    button.setObjectName("browseClose")
    button.setFixedSize(CLOSE_PX, CLOSE_PX)
    button.setAutoDefault(False)
    button.setToolTip("Close")
    return button


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
                 run_job, install, switch_version, is_busy, app_version=None, parent: QWidget | None = None) -> None:
        """`game`: the ThunderstoreGame (community slug). `installed()` ->
        the open load order's full_name -> entry dict (read live, it grows
        with every install; each entry's "version" is what's on disk);
        `framework`: its framework's full_name. `run_job(name, fn,
        on_done)`: the screen's _run_job. `install(ref, on_done, parent)`:
        the screen's install job (on_done({"ok": ...} or {"error": ...})
        after the screen refreshed); `switch_version(full_name, version |
        None, on_done, parent)`: its in-place re-install at that version
        (None = the latest). `is_busy()`: the screen's mutating-job lock."""
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
        self._closed = False
        # browse state
        self._query = ""
        self._ordering = INITIAL_ORDERING
        self._category = None  # a category id, or None for all
        self._page = 1
        self._pages = 1
        self._gen = 0  # bumped per listing request; a reply from an older one is dropped
        self._page_cache: dict[tuple, dict] = {}  # (query, ordering, category, page) -> PagedListing.page result
        self._listings: dict[tuple, tb.PagedListing] = {}  # (query, ordering, category) -> its PagedListing
        self._cards: list[_Card] = []
        self._categories: list[dict] = []
        self._installing: str | None = None  # full_name of the install / switch in flight
        self._installing_version: str | None = None  # the version a switch is heading for (None = an install / the latest)
        # detail state
        self._detail_listing: dict | None = None  # the card's listing (namespace / name / icon_url / ...)
        self._detail: dict | None = None  # fetch_listing_detail's dict (the LATEST version: the right column)
        self._detail_gen = 0
        self._versions: list[dict] = []  # fetch_versions rows, newest first
        self._version: str | None = None  # the selected version (the header's picker)
        self._version_meta: dict | None = None  # fetch_version of the selected version
        self._chain: dict | None = None  # dependency_chain for the selected version
        self._has_changelog = False
        self._tab = "details"
        self._version_buttons: list[tuple[str, QPushButton]] = []  # Versions tab: (version, its Install)
        self._dep_icons: list[tuple[str, QLabel]] = []  # Required tab: (icon_url, label)
        # icons: url -> QPixmap (null when the fetch failed), session-lived
        self._icons: dict[str, QPixmap] = {}
        self._icon_loader = _IconLoader(app_version)
        self._icon_loader.loaded.connect(self._on_icon, Qt.ConnectionType.QueuedConnection)

        layout = QVBoxLayout(self)  # .modal: padding 16px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_browse_page())
        self.stack.addWidget(self._build_detail_page())
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
        self.back_button.clicked.connect(lambda _=False: self._show_browse())
        self.version_combo.currentIndexChanged.connect(lambda _i: self._version_changed())
        self.detail_install_button.clicked.connect(lambda _=False: self._install_from_detail())
        self.copy_button.clicked.connect(lambda _=False: self._copy_package_name())
        self.retry_button.clicked.connect(lambda _=False: self._retry_detail())
        self.close_button.clicked.connect(lambda _=False: self.reject())
        self.detail_close_button.clicked.connect(lambda _=False: self.reject())

        log(f"browse window opened ({game.community}, load order {load_order_name!r})")
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
        self.close_button = _close_button()
        header.addWidget(self.close_button)
        layout.addLayout(header)

        filters = QHBoxLayout()  # .filter-row
        filters.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search mods...")
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.search, 1)
        self.category_combo = QComboBox()
        self.category_combo.addItem("Category: All", None)
        self.category_combo.setMinimumWidth(180)
        filters.addWidget(self.category_combo)
        self.sort_combo = QComboBox()
        for value, label in tb.ORDERINGS:
            self.sort_combo.addItem(f"Sort: {label}", value)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(INITIAL_ORDERING)))
        self.sort_combo.setMinimumWidth(180)
        filters.addWidget(self.sort_combo)
        layout.addLayout(filters)

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
        self.page_label = QLabel("")
        self.page_label.setProperty("muted", True)
        pagination.addWidget(self.prev_button)
        pagination.addWidget(self.page_label)
        pagination.addWidget(self.next_button)
        pagination.addStretch(1)
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

        body = QHBoxLayout()  # left: header card + tabs | right: the facts column
        body.setSpacing(MODAL_GAP)
        left = QVBoxLayout()
        left.setSpacing(MODAL_GAP)
        left.addWidget(self._build_header_card())
        left.addLayout(self._build_tab_bar())
        left.addWidget(self._build_tab_body(), 1)
        body.addLayout(left, 1)
        body.addWidget(self._build_right_column())
        layout.addLayout(body, 1)
        return page

    def _build_header_card(self) -> QFrame:
        card = _panel()
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 14, 14, 14)
        row.setSpacing(16)
        self.detail_icon = QLabel()
        self.detail_icon.setProperty("role", "browse-icon")
        self.detail_icon.setFixedSize(DETAIL_ICON_PX, DETAIL_ICON_PX)
        self.detail_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.detail_icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
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
        self.detail_stats = QLabel()  # the green line: ⬇ · ★ · size
        self.detail_stats.setProperty("muted", True)
        names.addWidget(self.detail_name)
        names.addWidget(self.detail_description)
        names.addWidget(self.detail_links)
        names.addWidget(self.detail_stats)
        names.addStretch(1)
        row.addLayout(names, 1)
        self.version_combo = QComboBox()  # top-right: drives Install, Required, Changelog
        self.version_combo.setFixedWidth(VERSION_PICKER_WIDTH)
        self.version_combo.setEnabled(False)
        row.addWidget(self.version_combo, 0, Qt.AlignmentFlag.AlignTop)
        return card

    def _build_tab_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.tab_buttons: dict[str, QPushButton] = {}
        for key, label in TABS:
            button = QPushButton(label)
            button.setProperty("variant", "browse-tab")
            button.setAutoDefault(False)
            button.clicked.connect(lambda _=False, key=key: self._select_tab(key))
            bar.addWidget(button)
            self.tab_buttons[key] = button
        bar.addStretch(1)
        return bar

    def _build_tab_body(self) -> QFrame:
        frame = _panel()
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(14, 12, 14, 12)
        self.tab_stack = QStackedWidget()
        outer.addWidget(self.tab_stack)
        # 0: the status page (loading / error + Retry)
        status = QWidget()
        status_layout = QVBoxLayout(status)
        status_layout.addStretch(1)
        self.detail_message = QLabel()
        self.detail_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_message.setWordWrap(True)
        status_layout.addWidget(self.detail_message)
        self.retry_button = QPushButton("Retry")
        self.retry_button.setAutoDefault(False)
        status_layout.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignHCenter)
        status_layout.addStretch(1)
        self.tab_stack.addWidget(status)
        # 1: Details = the README over the dependency block
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(10)
        self.readme = _Readme("browseReadme")
        details_layout.addWidget(self.readme, 1)
        divider = QFrame()
        divider.setObjectName("browseDivider")
        divider.setFixedHeight(1)
        details_layout.addWidget(divider)
        self.deps_label = QLabel()
        self.deps_label.setProperty("muted", True)
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
        # 4: Changelog
        self.changelog = _Readme("browseReadme")
        self.tab_stack.addWidget(self.changelog)
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
        self.copy_button = QPushButton("⧉")
        self.copy_button.setObjectName("browseCopy")
        self.copy_button.setAutoDefault(False)
        self.copy_button.setToolTip("Copy the package name")
        copy_row.addWidget(self.copy_button)
        layout.addWidget(copybox)
        # the facts rows
        facts = _panel()
        rows = QVBoxLayout(facts)
        rows.setContentsMargins(0, 4, 0, 4)
        rows.setSpacing(0)
        self.fact_values: dict[str, QLabel] = {}
        for key, title in (("latest", "Latest version"), ("updated", "Last updated"), ("uploaded", "First uploaded"),
                           ("downloads", "Downloads"), ("likes", "Likes"), ("size", "Size"), ("dependants", "Dependants")):
            row = QFrame()
            row.setProperty("role", "browse-fact")
            row.setProperty("last", key == "dependants")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)
            row_layout.setSpacing(8)
            label = QLabel(title)
            label.setProperty("muted", True)
            value = QLabel("-")
            value.setProperty("role", "browse-fact-value")
            value.setTextFormat(Qt.TextFormat.RichText if key in ("dependants", "updated") else Qt.TextFormat.PlainText)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        title = QLabel("Categories")
        title.setProperty("role", "pane-title")
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
        key = (self._query, self._ordering, self._category, self._page)
        self._gen += 1
        gen = self._gen
        cached = self._page_cache.get(key)
        if cached is not None:
            log(f"browse: page {self._page} from the window's cache (q={self._query!r}, {self._ordering}, category={self._category})")
            self._show_page(cached)
            return
        self._clear_cards()
        self._show_message("Loading...")
        self._set_pagination(False)
        query, ordering, category, page = key
        listing = self._listings.get(key[:3])
        if listing is None:
            listing = self._listings[key[:3]] = tb.PagedListing(
                self.game.community, query=query, ordering=ordering, category=category, app_version=self.app_version)

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
            self._show_page(result)

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
        self.page_label.setText(f"Page {self._page} of {self._pages}" if ready else "")
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
            self._apply_icon((self.detail_icon, DETAIL_ICON_PX), pixmap)
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
                elif self._installing == full and version == self._installing_version:
                    button.setText("Installing..." if have is None else "Switching...")
                    button.setEnabled(False)
                else:
                    button.setText(f"Install {version}")
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
        self._has_changelog = False
        self._detail_gen += 1
        gen = self._detail_gen
        log(f"browse: detail {listing['full_name']}")
        self.detail_name.set_text(listing["name"])
        self.detail_description.setText(listing["description"] or "")
        self._set_links(listing["namespace"], "")
        self.detail_stats.setText(stats_text(listing["download_count"], listing["rating_count"], listing["size"]))
        self.detail_icon.clear()
        self._show_icon((self.detail_icon, DETAIL_ICON_PX), listing["icon_url"])
        self._set_version_combo(None, "Version: loading...")
        self._set_facts(None)
        self.package_name_edit.setText(listing["full_name"])
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

    def _run_detail_job(self, gen: int, listing: dict, *, version: str | None) -> None:
        """The detail job. version=None: the whole page (listing detail,
        versions, the latest version's pieces); a version: just that
        version's metadata, README, changelog and chain."""
        community, app_version = self.game.community, self.app_version
        ns, name = listing["namespace"], listing["name"]
        installed = set(self._installed())
        framework = self._framework
        has_changelog = self._has_changelog

        def job(report):
            out: dict = {}
            if version is None:
                detail = tb.fetch_listing_detail(community, ns, name, app_version)
                versions = tb.fetch_versions(ns, name, app_version)
                if not any(v["version"] == detail["latest_version"] for v in versions):
                    versions.insert(0, {"version": detail["latest_version"], "created": detail["last_updated"], "downloads": 0})
                out.update(detail=detail, versions=versions)
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
            images = tb.prefetch_images(readme, app_version)
            if changelog:
                images.update(tb.prefetch_images(changelog, app_version))
            chain = tb.dependency_chain(meta["dependencies"], installed, framework, app_version)
            out.update(version=picked, meta=meta, readme=readme, changelog=changelog, images=images, chain=chain)
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
            self._show_detail(payload["ok"])

        self._run_job(f"browse-detail-{ns}-{name}" + (f"-{version}" if version else ""), job, done)

    def _show_detail(self, res: dict) -> None:
        listing = self._detail_listing
        if "detail" in res:  # the package-level pieces: right column, header, versions
            self._detail = res["detail"]
            self._versions = res["versions"]
            self._has_changelog = self._detail["has_changelog"]
            d = self._detail
            self.detail_description.setText(d["description"] or listing["description"] or "")
            self.detail_stats.setText(stats_text(d["download_count"], d["rating_count"], d["size"]))
            if d["icon_url"] and d["icon_url"] != listing["icon_url"]:
                listing["icon_url"] = d["icon_url"]
                self._show_icon((self.detail_icon, DETAIL_ICON_PX), listing["icon_url"])
            self._set_version_combo(self._versions, None)
            self._set_facts(d)
            self.package_name_edit.setText(d["full_version_name"])
            self._set_chips(d["categories"])
            self._fill_versions_tab()
            self.tab_buttons["changelog"].setVisible(self._has_changelog)
        self._version = res["version"]
        self._version_meta = res["meta"]
        website = (self._detail["website_url"] if self._detail else "") or res["meta"]["website_url"]
        self._set_links(listing["namespace"], website)
        self.readme.set_markdown(res["readme"], res["images"], fallback=res["meta"]["description"] or listing["description"])
        if self._has_changelog:
            self.changelog.set_markdown(res["changelog"], res["images"], fallback="No changelog for this version.")
        self._set_deps(res["chain"])
        self._fill_required_tab()
        self._select_tab(self._tab if self._tab != "changelog" or self._has_changelog else "details")  # off the status page
        self._apply_detail_button()

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
        parts = [link_html(tb.team_page_url(self.game.community, namespace), f"👥 {namespace}")]
        if website:
            parts.append(link_html(website, f"🔗 {shown_url(website)}"))
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
        f["dependants"].setToolTip("Opens the list of mods that depend on this one on thunderstore.io")

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

    def _select_tab(self, key: str) -> None:
        self._tab = key
        for k, button in self.tab_buttons.items():
            selected = k == key
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                _repolish(button)
        if self._version_meta is not None:  # loaded: show the tab; loading / error keep the status page
            self.tab_stack.setCurrentIndex(TAB_INDEX[key])

    def _show_status(self, text: str, *, error: bool) -> None:
        self.detail_message.setText(text)
        role = "modal-error" if error else None
        if self.detail_message.property("role") != role or self.detail_message.property("muted") != (not error):
            self.detail_message.setProperty("role", role)
            self.detail_message.setProperty("muted", not error)
            _repolish(self.detail_message)
        self.retry_button.setVisible(error)
        self.tab_stack.setCurrentIndex(0)

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

    def _set_deps(self, chain: dict | None) -> None:
        """The Details tab's dependency block (Option X, the full block): one
        row per dependency - ✓ already installed, ↓ will be pulled in
        (accent), ⚠ a problem (warn)."""
        self._chain = chain
        _clear_layout(self.deps_layout)
        if chain is None:
            self.deps_label.setText("Requires: checking dependencies...")
            return
        rows = ([("✓", n, "already installed", None) for n in chain["satisfied"]]
                + [("↓", n, "will be downloaded and installed too", "browse-dep-missing") for n in chain["missing"]]
                + [("⚠", n, msg, "browse-dep-problem") for n, msg in chain["problems"]])
        if not rows:
            self.deps_label.setText("Requires: nothing else - no dependencies.")
            return
        self.deps_label.setText("Requires (installed automatically with this mod):")
        for mark, name, text, role in rows:
            label = QLabel(f"{mark} {name} — {text}")
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            if role:
                label.setProperty("role", role)
            self.deps_layout.addWidget(label)

    def _dep_status(self, full_name: str) -> tuple[str, str]:
        """(pill text, pill state) of a dependency for the Required tab."""
        chain = self._chain or {"satisfied": [], "missing": [], "problems": []}
        if full_name in chain["satisfied"] or full_name in self._installed() or full_name == self._framework:
            return "Already installed", "ok"
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
            empty = QLabel("This package has no dependencies.")
            empty.setProperty("muted", True)
            self.required_layout.addWidget(empty)
            self.required_layout.addStretch(1)
            return
        for r in rows:
            row = QFrame()
            row.setProperty("role", "browse-row")
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
            version = QLabel(f"Version: <span style='color:{theme.ACCENT}'>{r['version'] or '?'}</span> (declared; installs the latest)")
            version.setTextFormat(Qt.TextFormat.RichText)
            version.setProperty("role", "browse-small")
            text.addWidget(version)
            layout.addLayout(text, 1)
            status, state = self._dep_status(r["full_name"])
            pill = QLabel(status)
            pill.setProperty("role", "browse-pill")
            pill.setProperty("state", state)
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
            self._set_button_text(button, "Install")
            button.setEnabled(False)
            return
        full, name, lo = listing["full_name"], listing["name"], self.load_order_name
        have = self._installed_version(full)
        latest = self._latest_version()
        idle = self._installing is None and not self._is_busy()
        if self._installing == full:
            text, enabled = f"{'Updating' if have is not None else 'Installing'} {name}...", False
        elif full == self._framework or (have is not None and (not latest or not ts.is_newer(latest, have))):
            text, enabled = f"{name} is already in {lo}", False
        elif have is not None:
            text, enabled = f"Update {name} to {latest} in {lo}", idle
        elif self._chain is None:
            text, enabled = install_label(name, 0, lo), False  # until the dependency chain is known
        else:
            text, enabled = install_label(name, len(self._chain["missing"]), lo), idle
        self._set_button_text(button, text)
        button.setEnabled(enabled)

    @staticmethod
    def _set_button_text(button: QPushButton, text: str) -> None:
        width = button.width() if button.width() > 50 else RIGHT_COLUMN_WIDTH
        label, changed = fit_button_text(text, button.fontMetrics(), width - BUTTON_TEXT_PADDING)
        button.setText(label)
        button.setToolTip(text if changed else "")

    # ---- pages ----
    def _show_browse(self) -> None:
        self._detail_gen += 1  # a detail reply arriving now is dropped
        self._detail_listing = None
        self._switch(0)
        self._apply_install_state()
        self.grid_scroll.setFocus()  # not the search box: Esc closes / Backspace idles from here

    def keyPressEvent(self, event) -> None:
        """Esc / Backspace: one level back (module docstring)."""
        key = event.key()
        on_detail = self.stack.currentIndex() == 1
        if key == Qt.Key.Key_Escape:
            if on_detail:
                log("browse: Esc -> back to results")
                self._show_browse()
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
                log("browse: Backspace -> back to results")
                self._show_browse()
            event.accept()
            return
        super().keyPressEvent(event)

    def _switch(self, index: int) -> None:
        """Shows a page with a short fade in (SCOPE.md §2: no instant cuts)."""
        page = self.stack.widget(index)
        self.stack.setCurrentIndex(index)
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.0)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", page)
        animation.setDuration(FADE_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.finished.connect(lambda: page.setGraphicsEffect(None))
        animation.start()
        self._fade = animation  # replaced by the next switch (the page owns it either way)

    # ---- lifecycle ----
    def done(self, result: int) -> None:
        self._closed = True
        self._icon_loader.stop()
        log(f"browse window closed ({len(self._page_cache)} pages viewed)")
        super().done(result)
        self.deleteLater()  # not kept around by the screen like the smaller modals: the page / icon caches die with it
