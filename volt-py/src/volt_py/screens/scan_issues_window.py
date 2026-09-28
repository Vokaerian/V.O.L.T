"""Scan issues window (port of ScanIssuesWindow.jsx): the folders the mod scan
(mods.scan_mod_roots) couldn't turn into a mod. A modal dialog: header with
Ignore / Folder / Close, then a rail (one entry per problem: short kind label
+ the path's base name) beside a detail pane for the selected entry (kind
label, message, full path, a static "why this happens" note).

Opened from the actions column's "N scan issue(s)" button
(RimWorldMainScreen._show_scan_issues). The problems list is owned by the
screen: Ignore goes through `on_ignore`, which persists the path, drops it
from the screen's list and hands back the new list for this window to show.

A duplicate-id pair whose About.xml names are identical can only be told
apart by their Steam Workshop listing titles (ScanIssuesWindow.jsx
workshopTitle / dupMessage): while such an entry is selected (both sides
Workshop items), both titles are looked up on a daemon thread - the
CollectionDialog pattern: a QObject carrier's queued signal brings the reply
back, and a reply for an entry no longer selected is ignored. The lookup is
the injected `title_lookup` (the screen binds workshop_title below to
steam_web_api's keyless GetPublishedFileDetails, falling back to the logged-in
Steam client, steam_client.workshop_item, only while Steam is available).
Results are cached for the app session (a failure too, as the JS). Resolved
titles replace the About.xml names in the entry's Kept / Ignored blocks; an
unresolved side keeps its name plus a neutral note (titleText).
"""

import re
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QSize, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from volt_py import paths
from volt_py.applog import log

# ScanIssuesWindow.jsx RAIL_LABEL (fallback 'Scan issue').
RAIL_LABEL = {
    "missing-folder": "Folder not found",
    "no-about": "Not a mod folder",
    "parse-error": "Unreadable About.xml",
    "duplicate-id": "Duplicate package ID",
}

# ScanIssuesWindow.jsx WHY: static note per kind, under the specific message.
# Scan order (paths.mod_roots): official, then Mods, then Workshop; first wins.
WHY = {
    "missing-folder":
        "This is one of the folders VOLT scans for mods (for example the game's Mods folder), but it doesn't "
        "exist. It may have been deleted, moved, or renamed since the last scan, or the game folder in Settings "
        "may be wrong.",
    "no-about":
        "This folder doesn't contain an About/About.xml file, so VOLT can't tell it's a mod. It may not be a mod "
        "folder at all, or its About.xml was deleted, moved, or renamed.",
    "parse-error":
        "This mod's About.xml exists but couldn't be read as valid XML. It may be corrupted, an incomplete "
        "download, or hand-edited incorrectly.",
    "duplicate-id":
        "Two different mod folders declare the same internal package ID, and RimWorld can only load one. VOLT "
        "keeps the first one it finds (official content, then your local Mods folder, then the Steam Workshop "
        "folder, in that order) and ignores the rest. This doesn't necessarily mean either mod is broken: it "
        "commonly happens when two different Workshop uploads are built from the same original mod and the fork "
        "never changed the internal ID.",
}

# .modal.validation-window: 900 x 600, at most the viewport minus 32px.
WINDOW_SIZE = (900, 600)
RAIL_WIDTH = 280  # .validation-body: grid-template-columns: 280px 1fr


LOOKING_UP = "Looking up Steam Workshop titles..."


def rail_label(problem: dict) -> str:
    return RAIL_LABEL.get(problem.get("kind"), "Scan issue")


def base_name(path) -> str:
    """ScanIssuesWindow.jsx baseName: last non-empty \\ or / segment, else the whole path."""
    s = str(path)
    return next((part for part in reversed(re.split(r"[\\/]", s)) if part), s)


# ---- Steam Workshop titles for a duplicate-id pair (pure logic, no Qt) ----
def needs_workshop_titles(problem: dict | None) -> bool:
    """ScanIssuesWindow.jsx needsWorkshopTitles: a duplicate-id pair with
    identical About.xml names, both sides Workshop items (mods.dup_side)."""
    if not problem or problem.get("kind") != "duplicate-id":
        return False
    kept, ignored = problem.get("kept"), problem.get("ignored")
    return bool(
        kept and ignored and kept.get("name") == ignored.get("name")
        and kept.get("workshop_id") and ignored.get("workshop_id")
    )


# ScanIssuesWindow.jsx titleCache: key -> {title, found, result[, error]},
# for the app session (not just one window). Key: the id for the Web API
# answer, "<id>+steam" for the answer with the Steam-client fallback tried, so
# a later lookup with Steam available still tries the fallback. A failed
# lookup is cached too (no retry this session); the About.xml names still show.
_title_cache: dict[str, dict] = {}
_title_lock = threading.Lock()


def workshop_title(
    wid: str,
    steam: bool,
    web_titles: Callable[[list[str]], list[dict]],
    client_item: Callable[[str], dict],
) -> dict:
    """ScanIssuesWindow.jsx workshopTitle, blocking (run it off the GUI
    thread). web_titles(ids): steam_web_api.get_published_file_details;
    client_item(id): steam_client.workshop_item, tried only with `steam` and
    only when the Web API says not found (a live item the keyless API reports
    as not found can still be visible there). Any fallback failure keeps the
    Web API answer. Never raises."""
    key = f"{wid}+steam" if steam else wid
    with _title_lock:
        hit = _title_cache.get(key)
    if hit is not None:
        return hit
    if steam:
        t = workshop_title(wid, False, web_titles, client_item)
        if not t["found"]:
            try:
                s = client_item(wid)
                if s and s.get("found") and s.get("title"):
                    t = {"title": s["title"], "found": True, "result": None}
            except Exception as err:  # SteamClientError (e.g. the DLL lacks the query exports) or anything else
                log(f"scan issues: Steam client title lookup for {wid} failed, keeping the Web API answer: {err}")
    else:
        try:
            d = next((d for d in web_titles([wid]) if d.get("id") == wid), None)
            t = (
                {"title": d.get("title") if d["found"] else None, "found": d["found"], "result": d.get("result")}
                if d else {"title": None, "found": False, "result": None}
            )
        except Exception as err:  # SteamWebApiError, or anything unexpected
            t = {"title": None, "found": False, "result": None, "error": str(err) or repr(err)}
    with _title_lock:
        # ponytail: two lookups of one id racing both hit Steam (JS shares one Promise); first answer wins.
        return _title_cache.setdefault(key, t)


def title_text(t: dict) -> str:
    """ScanIssuesWindow.jsx titleText: the listing title, or a neutral note.
    Deliberately no guess at why (removed / private / banned): the raw
    EResult is shown instead."""
    if t.get("title"):
        return t["title"]
    if t.get("error"):
        return f"(Steam title lookup failed: {t['error']})"
    if t.get("found"):
        return "(Steam returned this item without a title)"
    result = t.get("result")
    return f"(Steam didn't return a title for this item{f', result code {result}' if result is not None else ''})"


def dup_message(problem: dict, ws: dict) -> str:
    """ScanIssuesWindow.jsx dupMessage: the duplicate-id message with each
    side's lookup (ws["kept"] / ws["ignored"]) folded into its own block - a
    resolved title replaces the About.xml name, an unresolved side keeps its
    name with the note on the line under it. The first paragraph (the
    package ID line) is the scan's own (mods.scan_mod_roots)."""

    def side(label: str, mod: dict, t: dict) -> str:
        if t.get("title"):
            return f"{label}: {t['title']}\n{mod['path']}"
        return f"{label}: {mod['name']}\n{title_text(t)}\n{mod['path']}"

    head = str(problem.get("message") or "").split("\n\n")[0]
    return (
        f"{head}\n\n{side('Kept', problem['kept'], ws['kept'])}"
        f"\n\n{side('Ignored', problem['ignored'], ws['ignored'])}"
    )


# ---- the lookup thread ----
class _TitlesDone(QObject):
    """Carries one pair's titles from its thread to the GUI thread (a queued
    connection). Payload: {"p": the problem, "kept", "ignored", "carrier"}."""

    done = Signal(object)


def _lookup_titles(lookup: Callable[[str], dict], problem: dict, carrier: _TitlesDone) -> None:
    """Thread body: both sides' titles, one after the other, then
    `carrier.done`. The thread must never die silently."""
    titles = {}
    for side in ("kept", "ignored"):
        try:
            titles[side] = lookup(problem[side]["workshop_id"])
        except Exception as err:  # workshop_title doesn't raise; a stand-in lookup might
            titles[side] = {"title": None, "found": False, "result": None, "error": str(err) or repr(err)}
    try:
        carrier.done.emit({"p": problem, **titles, "carrier": carrier})
    except RuntimeError as err:  # shutting down: the Qt side is already gone
        log(f"scan issues: could not signal the window with the Workshop titles ({err!r})")


def _repolish(widget: QWidget) -> None:
    # A property selector isn't re-evaluated on its own after the first polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _text(role: str | None = None, *, muted: bool = False) -> QLabel:
    # Plain text: messages/paths can contain '<' (XML parse errors, folder names).
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


def _header_button(text: str) -> QPushButton:
    button = QPushButton(text)
    # No Enter-activates-default in this dialog: with autoDefault on, the first
    # button (Ignore) would become the default and Enter would ignore an issue.
    button.setAutoDefault(False)
    return button


class _RailEntry(QPushButton):
    """A rail entry (button.validation-entry.scan): kind label over the
    path's base name. Two text colors, so two labels over an empty button."""

    def __init__(self, problem: dict) -> None:
        super().__init__()
        self.setProperty("variant", "scan-entry")
        self.setAutoDefault(False)
        layout = QVBoxLayout(self)
        # padding 2px 8px (theme.py draws the 3px left bar as a border, so
        # 3 + 5 keeps the text 8px in, as under CSS's inset box-shadow).
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(0)
        self.target = QLabel()
        self.target.setProperty("role", "scan-target")
        for label, text in ((QLabel(), rail_label(problem)), (self.target, base_name(problem["path"]))):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(text)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(label)

    # QPushButton sizes itself from its own (empty) text; size from the two labels instead.
    def sizeHint(self) -> QSize:
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.layout().minimumSize()

    def set_selected(self, selected: bool) -> None:
        for widget in (self, self.target):
            if widget.property("selected") != selected:
                widget.setProperty("selected", selected)
                _repolish(widget)


class ScanIssuesWindow(QDialog):
    def __init__(
        self,
        problems: list[dict],
        on_ignore: Callable[[str], list[dict] | None],
        parent: QWidget | None = None,
        *,
        title_lookup: Callable[[str], dict] | None = None,
    ) -> None:
        """on_ignore(path): persists the ignore and returns the screen's new
        problems list, or None if it failed (the screen reports that itself).
        title_lookup(workshop_id) -> {title, found, result[, error]}: blocking
        (runs on a worker thread), never raises - workshop_title bound to the
        Steam calls; None turns the duplicate-id title lookup off."""
        super().__init__(parent)
        self.setObjectName("scanIssues")
        self.setWindowTitle("Scan issues")
        self.setModal(True)
        self._on_ignore = on_ignore
        self._problems: list[dict] = []
        self._sel_idx = 0
        self._error: str | None = None
        self._entries: list[_RailEntry] = []
        self._title_lookup = title_lookup
        # ScanIssuesWindow.jsx wsTitles: None, "loading", or {"p", "kept",
        # "ignored"}; _ws_for is the problem it belongs to (the JS effect's sel).
        self._ws: dict | str | None = None
        self._ws_for: dict | None = None
        # Each lookup in flight: its carrier (kept alive until its queued
        # `done` has been delivered) and its thread.
        self._lookups: dict[_TitlesDone, threading.Thread] = {}

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()  # .validation-head (.scan-issues: gap 8px, h2 flex 1)
        header.setSpacing(8)
        title = QLabel("Scan issues")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.ignore_button = _header_button("Ignore")
        self.folder_button = _header_button("Folder")
        self.close_button = _header_button("Close")
        for button in (self.ignore_button, self.folder_button, self.close_button):
            header.addWidget(button)
        layout.addLayout(header)

        # .validation-body: rail | detail. Replaced by the empty message when
        # there's nothing to show (the header stays).
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_detail(), 1)
        layout.addWidget(self._body, 1)
        self._empty = QLabel("No scan issues.")
        self._empty.setProperty("muted", True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._empty, 1)

        self.ignore_button.clicked.connect(lambda: self._ignore())
        self.folder_button.clicked.connect(lambda: self._open_folder())
        self.close_button.clicked.connect(lambda: self.reject())  # Esc rejects too (QDialog default)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        self.set_problems(problems)
        self.close_button.setFocus()

    # ---- layout ----
    def _build_rail(self) -> QScrollArea:
        # .validation-rail: --panel-2, border, radius, padding 4px 0, scrolls
        # (both ways: overflow-y auto makes overflow-x auto too).
        scroll = self._rail_scroll = QScrollArea()
        scroll.setObjectName("scanRail")
        scroll.setFixedWidth(RAIL_WIDTH)
        scroll.setWidgetResizable(True)
        inner = QWidget()
        self._rail = QVBoxLayout(inner)
        self._rail.setContentsMargins(0, 4, 0, 4)
        self._rail.setSpacing(0)
        self._rail.addStretch(1)
        scroll.setWidget(inner)
        # Let the rail's background show through (setWidget turns autofill on).
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return scroll

    def _build_detail(self) -> QScrollArea:
        # .validation-detail: --panel, border, radius, padding 10px, scrolls.
        scroll = QScrollArea()
        scroll.setObjectName("scanDetail")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        detail = QVBoxLayout(inner)
        detail.setContentsMargins(10, 10, 10, 10)
        detail.setSpacing(0)  # .modal p { margin: 0 }
        self._heading = QLabel()  # h3
        self._heading.setTextFormat(Qt.TextFormat.PlainText)
        self._heading.setProperty("role", "scan-heading")
        self._heading.setContentsMargins(0, 0, 0, 6)  # h3 margin: 0 0 6px
        self._message = _text(muted=True)
        self._looking_up = _text(muted=True)
        self._looking_up.setText(LOOKING_UP)
        self._path = _text("scan-mono")
        self._error_label = _text("scan-error")
        self._why = _text(muted=True)
        # p.scan-why: margin-top 1lh (one blank line).
        self._why.setContentsMargins(0, self._why.fontMetrics().lineSpacing(), 0, 0)
        for widget in (self._heading, self._message, self._looking_up, self._path, self._error_label, self._why):
            detail.addWidget(widget)
        detail.addStretch(1)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return scroll

    # ---- state ----
    def _sel(self) -> dict | None:
        """The selected problem. Out of range (e.g. Ignore removed the last
        entry) falls back to the first, as in the Electron window."""
        if 0 <= self._sel_idx < len(self._problems):
            return self._problems[self._sel_idx]
        return self._problems[0] if self._problems else None

    def set_problems(self, problems: list[dict]) -> None:
        self._problems = list(problems)
        for entry in self._entries:
            self._rail.removeWidget(entry)
            entry.deleteLater()
        self._entries = []
        for i, problem in enumerate(self._problems):
            entry = _RailEntry(problem)
            entry.clicked.connect(lambda _=False, i=i: self._select(i))
            self._rail.insertWidget(i, entry)  # before the trailing stretch
            self._entries.append(entry)
        self._render()

    def _select(self, index: int) -> None:
        self._sel_idx = index
        self._error = None
        self._render()

    def _render(self) -> None:
        sel = self._sel()
        if sel is not self._ws_for:  # the JS effect on [sel]: a new selection drops the old titles
            self._ws_for, self._ws = sel, None
            if self._title_lookup is not None and needs_workshop_titles(sel):
                self._start_title_lookup(sel)
        self.ignore_button.setEnabled(sel is not None)
        self.folder_button.setEnabled(sel is not None and sel.get("kind") != "missing-folder")
        self._body.setVisible(sel is not None)
        self._empty.setVisible(sel is None)
        for entry, problem in zip(self._entries, self._problems):
            entry.set_selected(problem is sel)
        if sel is None:
            return
        kind = sel.get("kind")
        self._heading.setText(rail_label(sel))
        ws = self._ws if isinstance(self._ws, dict) and self._ws["p"] is sel else None
        self._message.setText(dup_message(sel, ws) if ws else str(sel.get("message") or ""))
        self._looking_up.setVisible(self._ws == "loading")
        self._path.setText(str(sel["path"]))
        self._error_label.setText(self._error or "")
        self._error_label.setVisible(bool(self._error))
        self._why.setText(WHY.get(kind, ""))
        self._why.setVisible(kind in WHY)

    # ---- Steam Workshop titles ----
    def _start_title_lookup(self, problem: dict) -> None:
        self._ws = "loading"
        kept, ignored = problem["kept"]["workshop_id"], problem["ignored"]["workshop_id"]
        log(f"scan issues: looking up Steam Workshop titles for {kept} / {ignored} ({problem['path']})")
        carrier = _TitlesDone()  # no parent: owned by _lookups and the thread
        carrier.done.connect(self._on_titles_done, Qt.ConnectionType.QueuedConnection)
        thread = threading.Thread(
            target=_lookup_titles, args=(self._title_lookup, problem, carrier),
            name=f"steam-titles-{kept}-{ignored}", daemon=True,
        )
        self._lookups[carrier] = thread
        thread.start()

    @Slot(object)
    def _on_titles_done(self, result: dict) -> None:
        """A pair's titles arrived (on the GUI thread, via a queued
        connection). Ignored when that entry is no longer selected."""
        self._lookups.pop(result.get("carrier"), None)
        p = result["p"]
        if p is not self._ws_for:
            log(f"scan issues: Workshop titles for {p['path']} arrived after the selection changed, ignored")
            return
        self._ws = {"p": p, "kept": result["kept"], "ignored": result["ignored"]}
        log(
            f"scan issues: Workshop titles for {p['path']}: kept {title_text(result['kept'])!r}, "
            f"ignored {title_text(result['ignored'])!r}"
        )
        self._render()

    # ---- actions ----
    def _ignore(self) -> None:
        sel = self._sel()
        if sel is None:
            return
        problems = self._on_ignore(str(sel["path"]))
        if problems is not None:
            self.set_problems(problems)

    def _open_folder(self) -> None:
        """Opens the selected problem's path in the OS file browser. A failure
        shows inline in this window (the Electron window's own error state),
        not as an app-wide warning."""
        sel = self._sel()
        if sel is None:
            return
        self._error = None
        path = sel["path"]
        try:
            paths.open_path(path)
        except OSError as err:
            log(f"scan issues: open folder {path} ({sel.get('kind')}) FAILED: {err!r}")
            self._error = str(err)
        else:
            log(f"scan issues: opened folder {path} ({sel.get('kind')})")
        self._render()
