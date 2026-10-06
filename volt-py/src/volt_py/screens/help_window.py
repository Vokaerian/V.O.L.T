"""Help window: a read-only reference of what each control does. A modal
dialog shaped like the Scan issues window (screens/scan_issues_window.py):
header with the title and Close, then a rail of entry names (alphabetical)
beside a detail pane for the selected entry (name, one-line summary, longer
explanation).

Game-agnostic on purpose (cross-game shell element, PLAN.md §7): the window
only knows the entry shape, never a game. Each game supplies its own list of
{"name": str, "short": str, "long": str} dicts (RimWorld's:
screens/rimworld_help_entries.py) and opens it with
`HelpWindow(entries, parent=self, report=...).exec()`.

Report a problem (0.6.24, PLAN.md §10 (i)): with `report` given, a button in
the header row, between the title and Close (an addition; nothing existing
moves), saves a zip the user can send to whoever is helping:
applog.write_report (report.txt + every log in <base>/logs/: volt.log(.prev),
volt-crash.log(.prev), apply.log(.prev) - applog.REPORT_FILES; the home folder
scrubbed). Stdlib zipfile, nothing uploaded. `report` = {"game": display
name, "slug": APP-ROOT slug, "game_dir": the game folder or None (only its
name goes in the note), "profile_label": "Profile" / "Load order",
"profile": the open one's name or None, "log_path": this run's app-wide
volt.log (applog.log_file) or None}.

Paragraphs and lists (0.6.28, PLAN.md §11 (g)): a long text is plain text
split on blank lines into paragraphs, each its own word-wrapped QLabel; a
line starting "1. " / "2. " ... or "- " is a list row with a hanging indent
(the number / bullet in a fixed-width label, the text wrapping beside it).
`text_blocks` (Qt-free) does the split, `TextBlocks` shows it; the
Thunderstore Warnings and errors window (bepinex_issues_window.py) reuses
both.

markup=True (0.6.32, the update dialog's release notes, update_flow.notes_text;
off everywhere else, so a "# " or "**" in other text stays as typed): a
"# Title" line is a heading row (marker "#", its own label in the
HEADING_ROLE text role, no marker column) and a row starting "**Lead.**"
shows that lead-in bold (a rich-text label, the rest HTML-escaped).
"""

import html
import re

import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from volt_py.applog import log, write_report
from volt_py.screens.error_box import show_error

# Paragraphs / lists (TextBlocks): the gap between paragraphs, between the
# rows of one paragraph (list rows), the marker column and its gap.
PARAGRAPH_GAP = 8
ROW_GAP = 4
MARKER_WIDTH = 20  # fits "10." at the 13px body size
MARKER_GAP = 6
_LIST_LINE = re.compile(r"(\d+\.|-)\s+(.+)")
_HEADING_LINE = re.compile(r"#{1,6}\s+(.+)")
_LEAD = re.compile(r"\*\*(.+?)\*\*(.*)")
HEADING_ROLE = "help-short"  # theme.py: 14px 600, the Help pane's own sub-heading (markup=True only)

# Same box as the Scan issues / Warnings and errors windows: 900 x 600, at
# most the parent window minus 32px.
WINDOW_SIZE = (900, 600)
RAIL_WIDTH = 240

REPORT_LABEL = "Report a problem..."
REPORT_TOOLTIP = "Save a file with VOLT's log to send to whoever is helping you. Nothing is uploaded."
REPORT_INTRO = (
    "VOLT saves a .zip file you can send to whoever is helping you. It holds VOLT's log for {game} (a "
    "step-by-step record of what VOLT did), its crash log if VOLT ever crashed, and a short note: VOLT's version, your Windows version, the game and "
    "the {label} name.\n\n"
    "The log can contain folder paths on your computer, such as where {game} is installed. Your Windows user "
    "folder is replaced with \"~\", so your user name isn't in those paths. Nothing is uploaded: you choose who "
    "gets the file."
)
REPORT_DONE = "Saved {name} in {folder}.\n\nSend this file to whoever is helping you (by email or chat, for example)."


def report_file_name(slug: str, when: datetime) -> str:
    """The save dialog's default name: volt-report-<game>-<YYYYMMDD-HHMMSS>.zip."""
    return f"volt-report-{slug}-{when:%Y%m%d-%H%M%S}.zip"


def report_fields(report: dict) -> list[tuple[str, object]]:
    """report.txt's lines: no paths, only the game folder's own name."""
    try:
        app = version("volt-py")
    except Exception:
        app = "unknown"
    game_dir = report.get("game_dir")
    return [
        ("VOLT version", app),
        ("Operating system", platform.platform()),
        ("Game", report.get("game")),
        ("Game folder name", Path(game_dir).name if game_dir else None),
        (report.get("profile_label") or "Profile", report.get("profile")),
        ("Saved", f"{datetime.now():%Y-%m-%d %H:%M:%S}"),
    ]


def sorted_entries(entries: list[dict]) -> list[dict]:
    """Alphabetical by name, case-insensitive."""
    return sorted(entries, key=lambda entry: entry["name"].casefold())


def text_blocks(text: str, markup: bool = False) -> list[list[tuple[str, str]]]:
    """`text` as paragraphs (split on blank lines), each a list of rows
    (marker, text): marker "" for a plain line, "1." / "2." ... for a
    numbered line, "\u2022" for a "- " line; with markup, "#" for a
    "# Title" line (the text without the #s)."""
    blocks = []
    for chunk in re.split(r"\n[ \t]*\n", text.strip()):
        rows = []
        for line in chunk.splitlines():
            line = line.strip()
            heading = _HEADING_LINE.fullmatch(line) if markup else None
            if heading:
                rows.append(("#", heading.group(1).strip()))
                continue
            match = _LIST_LINE.fullmatch(line)
            if match:
                rows.append(("\u2022" if match.group(1) == "-" else match.group(1), match.group(2)))
            elif line:
                rows.append(("", line))
        if rows:
            blocks.append(rows)
    return blocks


def _repolish(widget: QWidget) -> None:
    # A property selector isn't re-evaluated on its own after the first polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _text(role: str | None) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    if role:
        label.setProperty("role", role)
    return label


class TextBlocks(QWidget):
    """A plain text shown as text_blocks: one selectable word-wrapped label
    per paragraph / list row (`role` / `muted` on every label, so the
    caller's QSS text rule applies; a markup heading takes HEADING_ROLE).
    setText rebuilds the rows."""

    def __init__(self, role: str | None = None, *, muted: bool = False, markup: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._role, self._muted, self._markup, self._raw = role, muted, markup, ""
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(0)
        self._rows: QWidget | None = None

    def text(self) -> str:
        return self._raw

    def _label(self, text: str, role: str | None = None) -> QLabel:
        label = _text(role or self._role)
        lead = _LEAD.fullmatch(text) if self._markup else None
        if lead:  # "**Lead.** rest" -> the lead-in bold, everything escaped (never raw ** or HTML)
            label.setTextFormat(Qt.TextFormat.RichText)
            text = f"<b>{html.escape(lead.group(1))}</b>{html.escape(lead.group(2))}"
        label.setText(text)
        if self._muted:
            label.setProperty("muted", True)
        return label

    def setText(self, text: str) -> None:
        self._raw = text
        if self._rows is not None:  # swap in a fresh container; the old one goes with its labels
            self._box.removeWidget(self._rows)
            self._rows.hide()
            self._rows.deleteLater()
        self._rows = QWidget()
        column = QVBoxLayout(self._rows)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(PARAGRAPH_GAP)
        for rows in text_blocks(text, self._markup):
            block = QVBoxLayout()
            block.setSpacing(ROW_GAP)
            for marker, line in rows:
                if marker in ("", "#"):
                    block.addWidget(self._label(line, HEADING_ROLE if marker else None))
                    continue
                row = QHBoxLayout()
                row.setSpacing(MARKER_GAP)
                mark = self._label(marker)
                mark.setFixedWidth(MARKER_WIDTH)
                mark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
                row.addWidget(mark)
                row.addWidget(self._label(line), 1)
                block.addLayout(row)
            column.addLayout(block)
        self._box.addWidget(self._rows)


def _transparent(scroll: QScrollArea) -> None:
    # Let the scroll area's own QSS background show through (setWidget turns autofill on).
    scroll.viewport().setAutoFillBackground(False)
    scroll.widget().setAutoFillBackground(False)


class HelpWindow(QDialog):
    def __init__(self, entries: list[dict], parent: QWidget | None = None, report: dict | None = None) -> None:
        super().__init__(parent)
        self._report = report
        self.setObjectName("help")
        self.setWindowTitle("Help")
        self.setModal(True)
        self._entries = sorted_entries(entries)
        self._buttons: list[QPushButton] = []
        self._sel_idx = -1

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel("Help")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.report_button = None
        if report is not None:
            self.report_button = QPushButton(REPORT_LABEL)
            self.report_button.setAutoDefault(False)
            self.report_button.setToolTip(REPORT_TOOLTIP)
            self.report_button.clicked.connect(lambda: self._save_report())
            header.addWidget(self.report_button)
        self.close_button = QPushButton("Close")
        self.close_button.setAutoDefault(False)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(8)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_detail(), 1)
        layout.addLayout(body, 1)

        self.close_button.clicked.connect(lambda: self.reject())  # Esc rejects too (QDialog default)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        if self._entries:
            self._select(0)
        self.close_button.setFocus()

    # ---- layout ----
    def _build_rail(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("helpRail")
        scroll.setFixedWidth(RAIL_WIDTH)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        rail = QVBoxLayout(inner)
        rail.setContentsMargins(4, 4, 4, 4)  # as the Rules window's rail
        rail.setSpacing(4)
        for i, entry in enumerate(self._entries):
            button = QPushButton(entry["name"])
            button.setProperty("variant", "help-entry")
            button.setAutoDefault(False)
            button.clicked.connect(lambda _=False, i=i: self._select(i))
            rail.addWidget(button)
            self._buttons.append(button)
        rail.addStretch(1)
        scroll.setWidget(inner)
        _transparent(scroll)
        return scroll

    def _build_detail(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("helpDetail")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        detail = QVBoxLayout(inner)
        detail.setContentsMargins(14, 12, 14, 12)
        detail.setSpacing(10)
        self._heading = _text("help-heading")
        self._short = _text("help-short")
        self._long = TextBlocks("help-long")  # paragraphs + lists (0.6.28)
        for label in (self._heading, self._short, self._long):
            detail.addWidget(label)
        detail.addStretch(1)
        scroll.setWidget(inner)
        _transparent(scroll)
        return scroll

    # ---- Report a problem ----
    def _save_report(self) -> None:
        """Says what goes in the file (paths included) first, then a save
        dialog (default name report_file_name, on the Desktop), then
        applog.write_report. Success names the file; a failure is the
        friendly error box."""
        r = self._report
        label = (r.get("profile_label") or "Profile").lower()
        box = QMessageBox(QMessageBox.Icon.Information, "Report a problem", REPORT_INTRO.format(game=r["game"], label=label),
                          QMessageBox.StandardButton.Cancel, self)
        save = box.addButton("Save report...", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(save)  # Enter goes on (the confirm convention, user decision 2026-09-29)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)  # Esc cancels
        box.exec()
        if box.clickedButton() is not save:
            log("report a problem: cancelled at the intro")
            return
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation) or str(Path.home())
        default = str(Path(folder) / report_file_name(r["slug"], datetime.now()))
        path, _ = QFileDialog.getSaveFileName(self, "Save problem report", default, "Zip files (*.zip)")
        if not path:
            log("report a problem: cancelled at the save dialog")
            return
        path = Path(path)
        try:
            names = write_report(path, report_fields(r), r.get("log_path"))
        except OSError as err:
            log(f"report a problem: writing {path} FAILED: {err!r}")
            show_error(self, "Report a problem", "Couldn't save the report.",
                       means="No file was saved.", tryit="Pick another folder (your Desktop, say) and try again.",
                       details=f"{path}\n{err}")
            return
        log(f"report a problem: saved {path} ({', '.join(names)})")
        QMessageBox.information(self, "Report a problem", REPORT_DONE.format(name=path.name, folder=path.parent))

    # ---- state ----
    def _select(self, index: int) -> None:
        self._sel_idx = index
        entry = self._entries[index]
        self._heading.setText(entry["name"])
        self._short.setText(entry["short"])
        self._long.setText(entry["long"])
        for i, button in enumerate(self._buttons):
            selected = i == index
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                _repolish(button)
