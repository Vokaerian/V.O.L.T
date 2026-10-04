"""Troubleshoot window for the Thunderstore/BepInEx manager (troubleshooting
phase 2, dispatch B, 0.6.38; PLAN.md §14, spec temp/troubleshoot-phase2/
SPEC.md §5; the signed-off mockup https://claude.ai/artifact/SxrxdohnFoGwze1KuNNcBz,
notes temp/handoff/2026-10-04-200500-troubleshoot-window-mockup.md). Opened by
the "Troubleshoot..." button at the right end of the screen's top bar. Advice
only: nothing here changes the profile.

A modal 900x600 dialog, "TROUBLESHOOT — <PROFILE>" + Close, two underline tabs
(Settings' tabs, on a frameless pane; sliding underline + page crossfade):

- "Log analyzer" (default): what went wrong in the last run, read from the
  profile's BepInEx/LogOutput.log by bepinex_log_analysis (via
  bepinex_troubleshoot.read_profile, a worker job: the window opens at once on
  "Reading the log..."). Headline (findings rated certain / likely), LAST RUN
  line, "Copy summary" (folder paths replaced by placeholders), "Show harmless
  messages too (N)", two banners (profile saved after the run; the game still
  running / closed since, + "Read the log again"), then the Warnings window's
  rail + detail: FIRST ERROR · LIKELY ROOT CAUSE (its cascade indented) /
  LATER PROBLEMS / HARMLESS; the detail reads CONFIDENCE (word pill + why) /
  MOD(S) (chips: jump to that mod in tab 2) / WHEN / TIMES, What happened /
  What it means / What to try, and "Technical details" (a recessed well,
  crossfaded open / shut) + "Copy details". Empty states: no log yet, clean run.
- "Mod contents": what each installed mod's DLLs are made of (the type index),
  a search, the Mods | Game methods segment (Game methods stays disabled until
  dispatch C's diagnostic run feeds a patch table through set_patch_table),
  the mods rail with "Share code with another mod" first, and the mod detail
  FILES / NAMESPACES / TYPES (+ Show all), the "Shares code with" callout
  (the duplicate-type check, CERTAIN; "See what this caused in the last run"
  jumps back to tab 1) and "Game code it changes" (the patch table, else a
  "No diagnostic run yet" box). Dispatch C (0.6.39): the stored patch table
  (bepinex_patchlog, read in the same worker job) feeds set_patch_table; the
  box's "Record patch details on next launch" sets the profile's switch (the
  same one as Settings > Troubleshooting > PATCH DETAILS) and turns into "Will
  record on the next launch" + "Don't record"; the game-method detail has
  CHANGED BY / CONFIDENCE, the Mod x kind table, What it means / What to try
  and the Harmony lines as technical details.

Run history (phase 4 dispatch D2, 0.6.42; spec temp/troubleshoot-phase4/
SPEC.md, the records are bepinex_runs.py's): the "Last run" row holds a run
selector - the game's log as it is now (newest; the only entry with the two
banners and "Read the log again") and the runs VOLT kept (the last 10), each
with its verdict word - and "Mark: worked / didn't work" for a kept run. A kept
run shows its findings AS STORED when it ended (never re-analysed against
today's mods). The rail's first section, "What changed since it last worked"
(or "... since the previous run"), lists bepinex_runs.diff_manifests against
the baseline (bepinex_runs.baseline) with its detail in the detail pane; rows
of findings new since the baseline get a "New since <time>" line. The live log
that VOLT has already kept (the game exited) is shown once, as the live entry,
with that kept run's mark and baseline.

Words and grouping live in volt_py/bepinex_troubleshoot.py (Qt-free, pinned by
tools/checks/volt_py_bepinex_troubleshoot.py)."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from volt_py import bepinex_patchlog as pl, bepinex_runs as runs, bepinex_troubleshoot as bt, painters, theme
from volt_py.applog import log
from volt_py.screens.details_panel import READOUT_KEY_WIDTH, details_key
from volt_py.screens.flow_layout import FlowLayout
from volt_py.screens.help_window import TextBlocks
from volt_py.screens.settings_window import underline_tabs

WINDOW_SIZE = (900, 600)
RAIL_WIDTH = 280
STRIP_SIZE = (340, 28)
CARD_WIDTH = 360
SECTION_GAP = 4  # a section label to its text (the Warnings window's)
PILL_SPACING = 0.08  # the confidence pill's letter spacing (em), the mockup's .pill
SECTIONS = ("What happened", "What it means", "What to try")
METHOD_ROLE = 256  # Qt.ItemDataRole.UserRole (a fixed Qt value; plain ints, so no enum arithmetic at import)
FILTER_ROLE = METHOD_ROLE + 1
MONO_NOTE = "Changes made with MonoMod hooks (On.* / DawnLib) aren't in this list."
PICKER_CHROME = 40  # the run selector's arrow (20) + padding + border, beyond its longest entry's text
PICKER_MIN_CHARS = 24  # it shrinks (eliding its text) to this before the row overflows a narrow window
CHANGE = "change:"  # rail keys of What changed rows (findings use their own ids)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _label(text: str = "", *, role: str | None = None, muted: bool = False, wrap: bool = True,
           select: bool = True) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    if select:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    if role:
        label.setProperty("role", role)
    if muted:
        label.setProperty("muted", True)
    return label


class _Elided(QLabel):
    """One line, elided at the right to its width (the rail's two lines)."""

    def __init__(self, text: str = "", role: str | None = None) -> None:
        super().__init__()
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if role:
            self.setProperty("role", role)
        self._full = ""
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, width))
                     if width > 0 else self._full)


def _pill(conf: str) -> QLabel:
    """The confidence word pill (theme.py QLabel[role="ts-pill"])."""
    pill = QLabel(conf)
    pill.setProperty("role", "ts-pill")
    pill.setProperty("conf", conf)
    pill.setFont(painters.terminal_font(10, PILL_SPACING))
    pill.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    pill.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return pill


def _chip(text: str, on_click, tip: str = "Show what this mod is made of") -> QPushButton:
    chip = QPushButton(text)
    chip.setProperty("variant", "ts-chip")
    chip.setAutoDefault(False)
    chip.setToolTip(tip)
    chip.setCursor(Qt.CursorShape.PointingHandCursor)
    chip.clicked.connect(lambda _=False: on_click())
    return chip


def _link(text: str, on_click, *, small: bool = True) -> QPushButton:
    link = QPushButton(text)
    link.setProperty("variant", "link")
    if small:
        link.setProperty("small", True)
    link.setAutoDefault(False)
    link.setCursor(Qt.CursorShape.PointingHandCursor)
    link.clicked.connect(lambda _=False: on_click())
    return link


class _Entry(QPushButton):
    """A rail row: title over a muted second line, a pill / tag at the right
    (theme.py QPushButton[variant="ts-entry"])."""

    def __init__(self, title: str, sub: str, *, severity: str = "none", indent: bool = False,
                 badge: QLabel | None = None, note: str | None = None) -> None:
        super().__init__()
        self.setProperty("variant", "ts-entry")
        self.setProperty("severity", severity)
        self.setProperty("selected", False)
        self.setAutoDefault(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(25 if indent else 9, 6, 10, 6)  # + the 3px bar: the mockup's 6/10/6/9 padding
        row.setSpacing(8)
        column = QVBoxLayout()
        column.setSpacing(1)
        self.title = _Elided(title)
        self.sub = _Elided(sub, "ts-sub")
        column.addWidget(self.title)
        column.addWidget(self.sub)
        self.note = None
        if note:  # run history: "New since 18:05 yesterday"
            self.note = _Elided(note, "ts-sub")
            column.addWidget(self.note)
        row.addLayout(column, 1)
        if badge is not None:
            row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

    def sizeHint(self):  # sized by its labels, not its (empty) text
        return self.layout().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize()

    def set_selected(self, on: bool) -> None:
        if self.property("selected") != on:
            self.setProperty("selected", on)
            _repolish(self)


def _section_label(text: str) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(10, 8, 10, 4)
    lay.addWidget(painters.TerminalLabel(text, rule="side"))
    return box


def _card(title: str, *lines: str) -> tuple[QWidget, QLabel, list[QLabel]]:
    """An empty-state card (the first-run card's look) centred with stretches
    (DESIGN.md §36's rule for a wrapped-text panel)."""
    holder = QWidget()
    outer = QVBoxLayout(holder)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.addStretch(1)
    row = QHBoxLayout()
    row.addStretch(1)
    card = QFrame()
    card.setProperty("role", "first-run-card")
    card.setFixedWidth(CARD_WIDTH)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 14, 14, 14)
    lay.setSpacing(8)
    head = _label(title, role="first-run-title")
    lay.addWidget(head)
    bodies = []
    for line in lines:
        body = _label(line, muted=True)
        lay.addWidget(body)
        bodies.append(body)
    row.addWidget(card)
    row.addStretch(1)
    outer.addLayout(row)
    outer.addStretch(1)
    return holder, head, bodies


def _well(text: QLabel) -> QFrame:
    """The recessed well (details_panel.details_well's frame, without its
    scroll area: it sits in the detail pane's own scroll)."""
    text.setObjectName("detailsWellText")
    well = QFrame()
    well.setObjectName("detailsWell")
    grid = QGridLayout(well)
    grid.setContentsMargins(1, 1, 1, 1)
    grid.setSpacing(0)
    grid.addWidget(text, 0, 0)
    shade = QWidget()
    shade.setObjectName("detailsWellShade")
    shade.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    shade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    shade.setFixedHeight(7)
    grid.addWidget(shade, 0, 0, Qt.AlignmentFlag.AlignTop)
    return well


class _Readout:
    """details_panel.readout's look for values that hold widgets: copper keys
    in a 108px column, a 1px rule between rows (theme.py ts-value)."""

    def __init__(self) -> None:
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(0)
        self.grid.setVerticalSpacing(0)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnMinimumWidth(0, READOUT_KEY_WIDTH)
        self._rows = 0

    def row(self, key: str, *, flow: bool = False):
        """Adds a row; returns its value layout (a FlowLayout for chips)."""
        first = self._rows == 0
        label = details_key(key)
        label.setProperty("readout", True)
        label.setProperty("first", first)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        cell = QFrame()
        cell.setProperty("role", "ts-value")
        cell.setProperty("first", first)
        lay = FlowLayout(cell, horizontal_spacing=6, vertical_spacing=4, center_rows=False) if flow else QHBoxLayout(cell)
        lay.setContentsMargins(0, 4, 2, 4)
        if not flow:
            lay.setSpacing(6)
        self.grid.addWidget(label, self._rows, 0)
        self.grid.addWidget(cell, self._rows, 1)
        self._rows += 1
        return lay


class TroubleshootWindow(QDialog):
    def __init__(self, game_name: str, profile: str, *, log_path, root, manifest: Callable[[], dict | None],
                 run_job, type_cache: dict, game_running: Callable[[], bool], places: dict, app_version: str,
                 parent: QWidget | None = None) -> None:
        """`log_path`: the profile's BepInEx/LogOutput.log; `root`: its tree
        root; `manifest()`: the open profile's loadorder.json dict as saved;
        `run_job(name, fn, on_done)`: the screen's worker jobs; `type_cache`:
        the screen's session cache of type-index scans (scan_key -> scan),
        merged back on the GUI thread; `game_running()`: this profile's modded
        run is live; `places`: {placeholder: folder} for redaction."""
        super().__init__(parent)
        self.setObjectName("troubleshoot")
        self.setWindowTitle(f"Troubleshoot {profile}")
        self.setModal(True)
        self._game, self._profile, self._version = game_name, profile, app_version
        self._log_path, self._root, self._manifest = log_path, root, manifest
        self._run_job, self._type_cache, self._game_running, self._places = run_job, type_cache, game_running, places
        self._gen = 0
        self._closed = False
        self._reading = False
        self._res: dict | None = None
        self._read_manifest: dict | None = None  # the manifest the last read used (What changed for the live log)
        self._entries: list[dict] = []  # the run selector: [{"key": "live" | run id, "rec": stored run | None, "text"}]
        self._view: dict | None = None  # what tab 1 shows (the selected entry): findings, counts, baseline, changes, new
        self._running_at_read = False
        self._changed_at: str | None = None
        self._sel_finding: str | None = None
        self._sel_mod: str | None = None
        self._tech_open = False
        self._show_all_types = False
        self._finding_entries: dict[str, _Entry] = {}
        self._mod_entries: dict[str, _Entry] = {}
        self._mod_rows: dict[str, dict] = {}
        self._targets: dict | None = None  # dispatch C's patch table {target: {package: {kind: n}}}
        self._patch_note = ""
        self._patch_rows: dict = {}  # {target: [[kind index, package, patch method]]} (the technical lines)
        self._patch_recorded: str | None = None  # "19:23 today"
        self._mtech_open = False  # a game method's technical details
        self._mode = "mods"

        layout = QVBoxLayout(self)  # .modal: padding 16, gap 10
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel(f"Troubleshoot — {profile}")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.close_button = QPushButton("Close")
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(lambda _=False: self.reject())
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.setProperty("frameless", True)
        underline_tabs(self.tabs, theme.PANEL)
        self.tabs.addTab(self._build_log_tab(), "Log analyzer")
        self.tabs.addTab(self._build_mods_tab(), "Mod contents")
        layout.addWidget(self.tabs, 1)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._apply_banners)
        self._poll.start()
        self.close_button.setFocus()
        self.read()

    # ---- tab 1: Log analyzer ----
    def _build_log_tab(self) -> QWidget:
        page = self._log_page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        summary = self._summary = QWidget()
        s = QVBoxLayout(summary)
        s.setContentsMargins(0, 0, 0, 0)
        s.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.headline = _label(role="first-run-title")
        row.addWidget(self.headline, 1)
        self.copied_note = _label(role="ts-small", muted=True, wrap=False, select=False)
        row.addWidget(self.copied_note)
        self.copy_button = QPushButton("Copy summary")
        self.copy_button.setAutoDefault(False)
        self.copy_button.setToolTip("Copies these findings as plain text, to paste into Discord or a bug report. "
                                    "Folder paths are left out.")
        self.copy_button.clicked.connect(lambda _=False: self._copy_summary())
        row.addWidget(self.copy_button)
        s.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(details_key("Last run"))
        self.run_picker = QComboBox()  # run history: the live log + the kept runs (the app's plain combo)
        self.run_picker.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.run_picker.setMinimumContentsLength(PICKER_MIN_CHARS)  # never widens the window: grows up to its text (_fit_picker)
        self.run_picker.setToolTip("The first entry is the game's log as it is now. The others are earlier runs of "
                                   "this profile that VOLT kept (the last 10), with what VOLT found when each ended.")
        self.run_picker.currentIndexChanged.connect(lambda i: self._on_pick(i))
        row.addWidget(self.run_picker, 1)
        self.mark_label = _label(role="ts-small", muted=True, wrap=False, select=False)
        row.addWidget(self.mark_label)
        self.mark_worked = _link("worked", lambda: self._mark("worked"))
        self.mark_worked.setToolTip("This run worked: later runs show what changed since this one.")
        self.mark_sep = _label("/", role="ts-small", muted=True, wrap=False, select=False)
        self.mark_didnt = _link("didn't work", lambda: self._mark("didnt"))
        self.mark_didnt.setToolTip("This run didn't work, even if it looked fine: it's never used as the run that worked.")
        self.mark_clear = _link("clear", lambda: self._mark(None))
        self.mark_clear.setToolTip("Remove your mark: VOLT decides again (mods loaded and played 5 minutes or more = "
                                   "probably worked).")
        for w in (self.mark_worked, self.mark_sep, self.mark_didnt, self.mark_clear):
            row.addWidget(w)
        row.addStretch(1)
        self.harmless_box = QCheckBox("Show harmless messages too")
        self.harmless_box.toggled.connect(lambda _on: self._on_harmless())
        row.addWidget(self.harmless_box)
        s.addLayout(row)
        col.addWidget(summary)
        self.changed_banner, self.changed_text, _ = self._banner(with_link=False)
        self.running_banner, self.running_text, self.reread_link = self._banner(with_link=True)
        col.addWidget(self.changed_banner)
        col.addWidget(self.running_banner)

        self.log_stack = QStackedWidget()
        busy, _h, _b = _card("Reading the log...", "VOLT reads the game's log and looks inside the mods' files. "
                                                   "The first time can take a few seconds.")
        self.no_log, self.no_log_title, _b = _card(f"No log yet for {self._profile}",
                                                   "The game writes a log every time it runs. Launch the game once with "
                                                   "this profile (the \"Modded\" button), then open Troubleshoot again.",
                                                   "The \"Mod contents\" tab works without a log.")
        self.clean, _h, (self.clean_text, _x) = _card("Nothing went wrong that VOLT can see", "",
                                                      "If something in the game still seems wrong, it may not show up "
                                                      "in the log.")
        body = QWidget()
        b = QHBoxLayout(body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(8)
        self.finding_rail, self._finding_list = self._rail_scroll("validationRail")
        b.addWidget(self.finding_rail)
        self.finding_detail = self._detail_scroll()
        b.addWidget(self.finding_detail, 1)
        for w in (busy, self.no_log, self.clean, body):
            self.log_stack.addWidget(w)
        col.addWidget(self.log_stack, 1)
        return page

    def _banner(self, *, with_link: bool):
        frame = QFrame()
        frame.setProperty("role", "ts-banner")
        row = QHBoxLayout(frame)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(10)
        text = _label()
        row.addWidget(text, 1)
        link = None
        if with_link:
            link = _link("Read the log again", self.read, small=False)
            row.addWidget(link, 0, Qt.AlignmentFlag.AlignVCenter)
        frame.setVisible(False)
        return frame, text, link

    def _rail_scroll(self, name: str) -> tuple[QScrollArea, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setObjectName(name)
        scroll.setFixedWidth(RAIL_WIDTH)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)
        lay.addStretch(1)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        return scroll, lay

    def _detail_scroll(self) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("validationDetail")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(QWidget())
        scroll.viewport().setAutoFillBackground(False)
        return scroll

    @staticmethod
    def _clear(lay: QVBoxLayout) -> None:
        while lay.count() > 1:  # keep the trailing stretch
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

    def _set_detail(self, scroll: QScrollArea, severity: str | None = None) -> QVBoxLayout:
        """A fresh detail page in `scroll` (the old one is deleted)."""
        if scroll.property("severity") != severity:
            scroll.setProperty("severity", severity)
            _repolish(scroll)
        old = scroll.takeWidget()  # not setWidget's immediate delete: the click that got here may come from it
        if old is not None:
            old.hide()
            old.deleteLater()
        inner = QWidget()
        inner.setAutoFillBackground(False)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)
        return lay

    # ---- tab 2: Mod contents ----
    def _build_mods_tab(self) -> QWidget:
        page = self._mods_page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        strip = self.search_strip = QFrame()
        strip.setObjectName("browseFilterStrip")
        strip.setProperty("fieldFocus", False)
        strip.setFixedSize(*STRIP_SIZE)
        s = QHBoxLayout(strip)
        s.setContentsMargins(1, 1, 1, 1)
        s.setSpacing(0)
        prompt = QLabel(">")
        prompt.setProperty("role", "strip-prompt")
        s.addWidget(prompt)
        self.search = QLineEdit()
        self.search.setProperty("strip", True)
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText("Search a mod, a file, a namespace or a type")
        self.search.textChanged.connect(lambda _t: self._apply_search())
        self.search.installEventFilter(self)
        s.addWidget(self.search, 1)
        bar.addWidget(strip)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.mods_seg = QPushButton("Mods")
        self.methods_seg = QPushButton("Game methods")
        group = QButtonGroup(self)
        for button, side in ((self.mods_seg, "left"), (self.methods_seg, "right")):
            button.setProperty("variant", "config-filter")
            button.setProperty("seg", side)
            button.setCheckable(True)
            button.setAutoDefault(False)
            group.addButton(button)
            seg.addWidget(button)
        self.mods_seg.setChecked(True)
        self.mods_seg.clicked.connect(lambda _=False: self._set_mode("mods"))
        self.methods_seg.clicked.connect(lambda _=False: self._set_mode("methods"))
        bar.addLayout(seg)
        bar.addStretch(1)
        self.patch_status = _label(role="ts-small", muted=True, wrap=False, select=False)
        bar.addWidget(self.patch_status)
        col.addLayout(bar)

        self.mods_stack = QStackedWidget()
        busy, _h, _b = _card("Reading the mods' files...", "VOLT looks inside each mod's DLL files.")
        body = self._mods_body = QWidget()
        b = QHBoxLayout(body)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(8)
        rail = QFrame()
        rail.setObjectName("configRail")
        rail.setFixedWidth(RAIL_WIDTH)
        r = QVBoxLayout(rail)
        r.setContentsMargins(1, 1, 1, 1)
        self.rail_stack = QStackedWidget()
        self.mod_rail, self._mod_list = self._rail_scroll("configRailList")
        self.mod_rail.setFixedWidth(RAIL_WIDTH - 2)
        self.rail_stack.addWidget(self.mod_rail)
        self.methods_view = QListView()
        self.methods_view.setObjectName("tsMethods")
        self.methods_view.setUniformItemSizes(True)
        self.methods_view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self._methods_model = QStandardItemModel(self)
        self._methods_proxy = QSortFilterProxyModel(self)
        self._methods_proxy.setSourceModel(self._methods_model)
        self._methods_proxy.setFilterRole(FILTER_ROLE)
        self._methods_proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.methods_view.setModel(self._methods_proxy)
        self.methods_view.selectionModel().currentChanged.connect(lambda cur, _prev: self._show_method(cur))
        self.rail_stack.addWidget(self.methods_view)
        r.addWidget(self.rail_stack)
        b.addWidget(rail)
        self.detail_stack = QStackedWidget()
        self.mod_detail = self._detail_scroll()
        self.method_detail = self._detail_scroll()
        self.detail_stack.addWidget(self.mod_detail)
        self.detail_stack.addWidget(self.method_detail)
        b.addWidget(self.detail_stack, 1)
        self.mods_stack.addWidget(busy)
        self.mods_stack.addWidget(body)
        col.addWidget(self.mods_stack, 1)
        self._apply_patch_state()
        return page

    def eventFilter(self, obj, event) -> bool:
        """The search strip shows the field's focus edge (Browse Mods' strip)."""
        if obj is self.search and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            on = event.type() == QEvent.Type.FocusIn
            if self.search_strip.property("fieldFocus") != on:
                self.search_strip.setProperty("fieldFocus", on)
                _repolish(self.search_strip)
        return super().eventFilter(obj, event)

    # ---- reading ----
    def read(self) -> None:
        """(Re)reads the log + the mods' files in a worker job."""
        if self._reading:
            return
        self._gen += 1
        gen = self._gen
        self._reading = True
        if self.reread_link is not None:
            self.reread_link.setEnabled(False)
        manifest = self._manifest()
        cache = dict(self._type_cache)  # the worker fills a copy; merged back on the GUI thread
        path, root = self._log_path, self._root
        running = self._game_running()
        self._fade(lambda: self._show_busy())
        log(f"[troubleshoot] read started (generation {gen}): {path} "
            f"({'exists' if Path(path).is_file() else 'no log yet'}), {len(cache)} cached type scans, "
            f"game running: {running}")

        def job(report):
            res = bt.read_profile(path, root, manifest, cache)
            table = pl.load_table(root) if root else None  # the stored patch table (~300 KB): read here, off the GUI thread
            res["patch"] = (table, pl.targets_view(table)) if table else None
            res["runs"] = runs.list_runs(root) if root else []  # run history: <= 10 small JSON files, unreadable ones skipped + logged
            res["gz"] = {r["id"]: (runs.runs_dir(root) / f"{r['id']}.log.gz").is_file() for r in res["runs"]}
            return res

        self._run_job(f"troubleshoot-read-{gen}", job, lambda payload: self._on_read(gen, manifest, running, payload))

    def _on_read(self, gen: int, manifest: dict | None, running: bool, payload: dict) -> None:
        res = payload.get("ok")
        added = 0
        if res is not None:
            added = len(res["cache"]) - len(self._type_cache)
            self._type_cache.update(res["cache"])  # useful even when this window is gone
        if self._closed or gen != self._gen:
            log(f"[troubleshoot] read {gen} dropped ({'window closed' if self._closed else 'a newer read started'})")
            return
        self._reading = False
        if self.reread_link is not None:
            self.reread_link.setEnabled(True)
        if res is None:
            log(f"[troubleshoot] read failed: {payload.get('error')}")
            res = {"run": None, "findings": [], "duplicates": [], "counts": {}, "mods": [], "ms": 0}
        self._res = res
        self._read_manifest = manifest
        self._running_at_read = running
        run = res["run"]
        self._changed_at = bt.profile_changed((manifest or {}).get("updated_at"), run["mtime"]) if run else None
        log(f"[troubleshoot] read {gen} done in {res['ms']} ms: "
            + (f"{run['lines']:,} log lines, " if run else "no log, ")
            + f"{len(res['findings'])} findings {res['counts']}, {len(res['duplicates'])} duplicate-type pairs, "
            f"{len(res['mods'])} mods, type cache +{max(0, added)}, {len(res.get('runs') or [])} kept runs"
            + (f", profile saved after the run ({self._changed_at})" if self._changed_at else ""))
        self._fade(self._render)

    def _fade(self, swap) -> None:
        """Both tabs' content changes under one crossfade (the visible page)."""
        page = self.tabs.currentWidget()
        if page is None or not self.isVisible():
            swap()
            return
        painters.crossfade(page, swap, theme.MOTION)

    def _show_busy(self) -> None:
        self._summary.setVisible(False)
        self.changed_banner.setVisible(False)
        self.running_banner.setVisible(False)
        self.log_stack.setCurrentIndex(0)
        self.mods_stack.setCurrentIndex(0)

    # ---- tab 1 state ----
    def _render(self) -> None:
        res = self._res
        self._mod_rows = {m["id"]: m for m in res["mods"]}
        self._entries = self._build_entries()
        self.run_picker.blockSignals(True)
        self.run_picker.clear()
        for e in self._entries:
            self.run_picker.addItem(e["text"])
        self.run_picker.setCurrentIndex(0)
        self.run_picker.blockSignals(False)
        self._fit_picker()
        if not self._entries:  # no log and no kept run
            self._view = None
            self._summary.setVisible(False)
            self.log_stack.setCurrentIndex(1)
        else:
            self._summary.setVisible(True)
            self._show_view(0)
        self._apply_banners()
        self._fill_mods()
        patch = res.get("patch")
        if patch:
            table, targets = patch
            self.set_patch_table(targets, pl.note_text(table), rows=table["methods"],
                                 recorded=pl.when_text(table.get("recorded_at")))
        else:
            self.set_patch_table(None)
        self.mods_stack.setCurrentIndex(1)

    # ---- run history: the selector, the view, marks ----
    def _build_entries(self) -> list[dict]:
        """The live log (when there is one) + the kept runs, newest first. A
        kept run that IS the live log (the game exited and VOLT kept it) is
        not listed twice: the live entry carries its mark and baseline."""
        res = self._res
        run, stored = res["run"], res.get("runs") or []
        live = next((r for r in stored if bt.same_run(run, r)), None) if run is not None else None
        out = []
        if run is not None:
            out.append({"key": "live", "rec": live, "text": bt.with_verdict(bt.last_run_text(run, self._running_at_read), live)})
        out += [{"key": r["id"], "rec": r, "text": bt.stored_run_text(r)} for r in stored if r is not live]
        return out

    def _fit_picker(self) -> None:
        """The selector grows up to its longest entry (the row's stretch takes
        the rest) and its list is never narrower than that entry."""
        fm = self.run_picker.fontMetrics()
        width = max((fm.horizontalAdvance(e["text"]) for e in self._entries), default=0) + PICKER_CHROME
        self.run_picker.setMaximumWidth(width)
        self.run_picker.view().setMinimumWidth(width)

    def _show_view(self, index: int) -> None:
        """Tab 1 for selector entry `index`: the live log's findings, or a kept
        run's as stored; its baseline, What changed and New tags."""
        e = self._entries[index]
        live, rec = e["key"] == "live", e["rec"]
        all_runs = self._res.get("runs") or []
        if live:
            findings, counts = self._res["findings"], self._res["counts"]
            me = {"volt_version": runs._version(), "findings": findings}  # analysed just now, by this VOLT
            manifest = rec["manifest"] if rec else runs.summarize(self._read_manifest)  # not kept yet: the profile as saved
        else:
            findings, counts = rec.get("findings") or [], rec.get("counts") or {}
            me, manifest = rec, rec.get("manifest")
        base, kind = runs.baseline(all_runs, rec["id"] if rec else None)
        changes = bt.change_items(runs.diff_manifests(base.get("manifest"), manifest)) if base else None
        new = runs.new_signatures(me, base)
        self._view = {"index": index, "live": live, "rec": rec, "findings": findings, "counts": counts, "base": base,
                      "kind": kind, "changes": changes, "new": new, "when": None if live else bt.run_when(rec)}
        log(f"[troubleshoot] run shown: {'the live log' if live else rec['id']}"
            + (f" (kept as {rec['id']})" if live and rec else "") + f", {len(findings)} findings; baseline "
            + (f"{base['id']} ({kind}), {len(changes)} kinds of change, {len(new)} new findings" if base else "none"))
        harmless = sum(1 for f in findings if f["group"] == "harmless")
        self.harmless_box.blockSignals(True)
        self.harmless_box.setText(f"Show harmless messages too ({harmless})")
        self.harmless_box.blockSignals(False)
        self.headline.setText(bt.headline(findings, counts, self._profile, self._view["when"]))
        self.copied_note.setText("")
        self._sel_finding = None
        self._apply_marks()
        self._fill_findings()

    def _on_pick(self, index: int) -> None:
        if index < 0 or self._view is None or index == self._view["index"] or index >= len(self._entries):
            return
        e = self._entries[index]
        log(f"[troubleshoot] run selected: {'the live log' if e['key'] == 'live' else e['key']} ({e['text']})")
        self._fade(lambda: (self._show_view(index), self._apply_banners()))

    def _apply_marks(self) -> None:
        """"Mark: worked / didn't work" for a kept run (the live log only once
        VOLT has kept it); "Marked: worked · clear" once marked."""
        rec = self._view["rec"] if self._view else None
        mark = rec.get("mark") if rec else None
        self.mark_label.setVisible(rec is not None)
        self.mark_label.setText(f"Marked: {bt.MARK_WORDS[mark]} ·" if mark in bt.MARK_WORDS else "Mark:")
        for w in (self.mark_worked, self.mark_sep, self.mark_didnt):
            w.setVisible(rec is not None and mark not in bt.MARK_WORDS)
        self.mark_clear.setVisible(rec is not None and mark in bt.MARK_WORDS)

    def _mark(self, mark: str | None) -> None:
        rec = self._view["rec"] if self._view else None
        if rec is None or self._root is None:
            return
        if not runs.mark_run(self._root, rec["id"], mark):
            log(f"[troubleshoot] marking run {rec['id']} {mark} FAILED")
            self.mark_label.setText("Couldn't save the mark ·")
            return
        rec["mark"] = mark  # the same dict as in the kept runs: verdicts and baselines see it from now on
        log(f"[troubleshoot] run {rec['id']} marked {mark or '(cleared)'}; verdict now {runs.verdict(rec)}")
        index = self._view["index"]
        e = self._entries[index]
        e["text"] = (bt.with_verdict(bt.last_run_text(self._res["run"], self._running_at_read), rec) if e["key"] == "live"
                     else bt.stored_run_text(rec))
        self.run_picker.setItemText(index, e["text"])
        self._fit_picker()
        self._apply_marks()  # this run's own baseline is an OLDER run: its rail doesn't change

    def _apply_banners(self) -> None:
        """The two banners; also the 1 s poll, so the game closing (or
        starting) while the window is open shows up."""
        if (self._closed or self._res is None or self._reading or self._res["run"] is None or self._view is None
                or not self._view["live"]):  # the banners are about the live log only
            for b in (self.changed_banner, self.running_banner):
                b.setVisible(False)
            return
        self.changed_banner.setVisible(bool(self._changed_at))
        if self._changed_at:
            self.changed_text.setText(bt.CHANGED_BANNER.format(at=self._changed_at))
        now = self._game_running()
        text = bt.RUNNING_BANNER if now else bt.CLOSED_BANNER if self._running_at_read else None
        if text != (self.running_text.text() if self.running_banner.isVisible() else None):
            self.running_text.setText(text or "")
            self.running_banner.setVisible(text is not None)
            if text:
                log(f"[troubleshoot] banner: {'game running' if now else 'game closed since the read'}")

    def _visible_findings(self) -> list[dict]:
        return [f for f, _i, _s in self._rail_items()]

    def _rail_items(self) -> list[tuple[dict, bool, str]]:
        return [item for _label, items in bt.rail_sections(self._view["findings"], self.harmless_box.isChecked())
                for item in items]

    def _fill_findings(self) -> None:
        v = self._view
        findings = v["findings"]
        sections = bt.rail_sections(findings, self.harmless_box.isChecked())
        self._clear(self._finding_list)
        self._finding_entries = {}
        widgets = []
        clean = bt.clean_text(self._profile, sum(1 for f in findings if f["group"] == "harmless"), v["when"])
        if v["changes"] is not None:  # run history: What changed, first (absent without a baseline)
            widgets.append(_section_label(bt.changes_title(v["kind"])))
            note = _label(bt.baseline_text(v["kind"], v["base"]) + ("" if v["changes"] else " " + bt.NO_CHANGES),
                          role="ts-small", muted=True)
            note.setContentsMargins(10, 0, 10, 4)
            widgets.append(note)
            for item in v["changes"]:
                entry = _Entry(item["title"], item["sub"])
                if item["muted"]:  # "reinstalled, same version": shown, but quiet
                    entry.title.setProperty("muted", True)
                entry.setToolTip(f"{item['title']}\n{item['sub']}")
                entry.clicked.connect(lambda _=False, k=CHANGE + item["key"]: self._select_finding(k))
                self._finding_entries[CHANGE + item["key"]] = entry
                widgets.append(entry)
        tag = bt.new_tag(v["base"]) if v["new"] else None
        for label, items in sections:
            widgets.append(_section_label(label))
            for f, indent, sub in items:
                severity = f["severity"] if f["severity"] in ("error", "warning") else "none"
                new = tag if (f.get("technical") or {}).get("signature") in v["new"] else None
                entry = _Entry(f["title"], sub, severity=severity, indent=indent, badge=_pill(f["confidence"]), note=new)
                entry.setToolTip("\n".join(x for x in (f["title"], sub, new) if x))
                entry.clicked.connect(lambda _=False, fid=f["id"]: self._select_finding(fid))
                widgets.append(entry)
                self._finding_entries[f["id"]] = entry
        if not sections and v["changes"]:  # a clean log, but the mods changed: the rail stays, with the clean words
            done = _label(clean, role="ts-small", muted=True)
            done.setContentsMargins(10, 8, 10, 4)
            widgets.append(done)
        for i, w in enumerate(widgets):
            self._finding_list.insertWidget(i, w)
        if not self._finding_entries:
            self.clean_text.setText(clean)
            self.log_stack.setCurrentIndex(2)
            return
        self.log_stack.setCurrentIndex(3)
        if self._sel_finding not in self._finding_entries:  # the root cause first, as before; else the first change
            self._sel_finding = next((k for k in self._finding_entries if not k.startswith(CHANGE)),
                                     next(iter(self._finding_entries)))
        self._show_finding()

    def _on_harmless(self) -> None:
        if self._res is None or self._view is None:
            return
        log(f"[troubleshoot] show harmless messages: {self.harmless_box.isChecked()}")
        self._fade(self._fill_findings)

    def _select_finding(self, fid: str) -> None:
        if fid == self._sel_finding:
            return
        self._sel_finding = fid
        log(f"[troubleshoot] finding selected: {fid}")
        self._show_finding()

    def _finding(self, fid: str | None) -> dict | None:
        return next((f for f in (self._view or {}).get("findings", ()) if f["id"] == fid), None)

    def _show_finding(self) -> None:
        for fid, entry in self._finding_entries.items():
            entry.set_selected(fid == self._sel_finding)
        if (self._sel_finding or "").startswith(CHANGE):
            self._show_change(self._sel_finding[len(CHANGE):])
            return
        f = self._finding(self._sel_finding)
        if f is None:
            return
        root = next((x for x in self._view["findings"] if x["group"] == "root"), None)
        lay = self._set_detail(self.finding_detail, f["severity"] if f["severity"] in ("error", "warning") else None)
        heading = painters.TerminalLabel(f["title"], rule="heading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        lay.addWidget(heading)
        ro = _Readout()
        row = ro.row("Confidence")
        row.addWidget(_pill(f["confidence"]), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(_label(f["why_confidence"], muted=True), 1)
        row = ro.row("Mods" if len(f["mods"]) > 1 else "Mod", flow=bool(f["mods"]))
        for mod, name in zip(f["mods"], f.get("mod_names") or f["mods"]):
            row.addWidget(_chip(name, lambda m=mod: self.jump_to_mod(m)))
        if not f["mods"]:  # a plain row: a wrapping label in a flow row would be laid out unwrapped
            named = f.get("plugins") or []
            row.addWidget(_label(f"The log names “{named[0]}”, which VOLT couldn't match to one installed mod."
                                 if named else "No mod is named in the error.", muted=True), 1)
        if f.get("also_involved"):  # the engine's later mod frames (an addition to the mockup's rows)
            row = ro.row("Also", flow=True)
            for mod in f["also_involved"]:
                name = self._name(mod)
                row.addWidget(_chip(name, lambda m=mod: self.jump_to_mod(m),
                                    "Also in the error's stack trace. Show what this mod is made of"))
        ro.row("When").addWidget(_label(bt.when_text(f, root)), 1)
        ro.row("Times").addWidget(_label(bt.times_text(f), role="ts-mono"), 1)
        lay.addLayout(ro.grid)
        for title, text in zip(SECTIONS, (f["what_happened"], f["what_it_means"], bt.steps_text(f["what_to_try"]))):
            section = QVBoxLayout()
            section.setSpacing(SECTION_GAP)
            section.addWidget(painters.TerminalLabel(title, rule="side"))
            blocks = TextBlocks()
            blocks.setText(text)
            section.addWidget(blocks)
            lay.addLayout(section)
        self._tech_link = _link("", self._toggle_tech)
        lay.addWidget(self._tech_link, 0, Qt.AlignmentFlag.AlignLeft)
        tech = self._tech_box = QWidget()
        t = QVBoxLayout(tech)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(8)
        t.addWidget(_well(_label(self._technical(f), role="ts-mono")))
        row = QHBoxLayout()
        copy = QPushButton("Copy details")
        copy.setProperty("small", True)
        copy.setAutoDefault(False)
        copy.setToolTip("Copies this finding and its technical details as plain text. Folder paths are left out.")
        copy.clicked.connect(lambda _=False: self._copy_details())
        row.addWidget(copy)
        self._details_note = _label(role="ts-small", muted=True, wrap=False, select=False)
        row.addWidget(self._details_note)
        row.addStretch(1)
        t.addLayout(row)
        lay.addWidget(tech)
        lay.addStretch(1)
        self._apply_tech()

    def _log_note(self) -> str:
        """"\n\n<why>" when the shown kept run's log isn't there, else ""."""
        rec = self._view["rec"] if self._view and not self._view["live"] else None
        note = bt.stored_log_note(rec, (self._res.get("gz") or {}).get(rec["id"], False)) if rec else None
        return f"\n\n{note}" if note else ""

    def _technical(self, f: dict) -> str:
        return bt.technical_text(f) + self._log_note()

    def _show_change(self, key: str) -> None:
        """A What changed row: the baseline in words, the mods (chips jump to
        Mod contents when the mod is still installed), what it means."""
        v = self._view
        item = next((i for i in v["changes"] or () if i["key"] == key), None)
        lay = self._set_detail(self.finding_detail)
        if item is None:
            lay.addStretch(1)
            return
        heading = painters.TerminalLabel(item["title"], rule="heading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        lay.addWidget(heading)
        lay.addWidget(_label(bt.baseline_text(v["kind"], v["base"]), muted=True))
        for full, name, detail in item["mods"]:
            row = QHBoxLayout()
            row.setSpacing(8)
            if full in self._mod_rows:
                row.addWidget(_chip(name, lambda m=full: self.jump_to_mod(m)))
            else:  # removed since: nothing to show in Mod contents
                row.addWidget(_label(name, wrap=False))
            row.addWidget(_label(detail, role="ts-mono", muted=True, wrap=False))
            row.addStretch(1)
            lay.addLayout(row)
        section = QVBoxLayout()
        section.setSpacing(SECTION_GAP)
        section.addWidget(painters.TerminalLabel("What it means", rule="side"))
        blocks = TextBlocks()
        blocks.setText(bt.change_means(key))
        section.addWidget(blocks)
        lay.addLayout(section)
        lay.addStretch(1)

    def _apply_tech(self) -> None:
        self._tech_link.setText("▾ Hide technical details" if self._tech_open else "▸ Technical details")
        self._tech_box.setVisible(self._tech_open)

    def _toggle_tech(self) -> None:
        self._tech_open = not self._tech_open
        log(f"[troubleshoot] technical details {'shown' if self._tech_open else 'hidden'}")
        painters.crossfade(self.finding_detail, self._apply_tech, theme.MOTION_FAST)  # a crossfade, never a height animation

    # ---- copying (paths redacted) ----
    def _copy(self, text: str) -> str:
        safe = bt.redact(text, self._places)
        QGuiApplication.clipboard().setText(safe)
        return safe

    def _copy_summary(self) -> None:
        if self._view is None:
            return
        v = self._view
        text = bt.summary_text(v["findings"], v["counts"], game=self._game, profile=self._profile,
                               version=self._version, last_run=self.run_picker.currentText(),
                               show_harmless=self.harmless_box.isChecked(), when=v["when"])
        safe = self._copy(text)
        self.copied_note.setText("Copied, without folder paths")
        log(f"[troubleshoot] summary copied: {len(safe)} characters, {len(self._visible_findings())} findings, "
            "folder paths replaced")

    def _copy_details(self) -> None:
        f = self._finding(self._sel_finding)
        if f is None:
            return
        safe = self._copy(bt.detail_text(f) + self._log_note())
        self._details_note.setText("Copied, without folder paths")
        log(f"[troubleshoot] details copied for {f['id']} ({f['family']}): {len(safe)} characters")

    # ---- tab 2: mods ----
    def _fill_mods(self) -> None:
        self._clear(self._mod_list)
        self._mod_entries = {}
        self._share_label = _section_label("")
        self._rest_label = _section_label("")
        self._no_hits = _label(muted=True)
        self._no_hits.setContentsMargins(12, 10, 12, 10)
        widgets = []
        rows = list(self._mod_rows.values())
        for title_box, group in ((self._share_label, [m for m in rows if m["shares"]]),
                                 (self._rest_label, [m for m in rows if not m["shares"]])):
            widgets.append(title_box)
            for m in group:
                tag = None
                if m["shares"]:
                    tag = QLabel("Shares code")
                    tag.setProperty("role", "ts-tag")
                    tag.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                entry = _Entry(m["name"], bt.mod_sub(m), badge=tag)
                entry.setToolTip(f"{m['name']} ({m['id']})")
                entry.clicked.connect(lambda _=False, mid=m["id"]: self._select_mod(mid))
                self._mod_entries[m["id"]] = entry
                widgets.append(entry)
        widgets.append(self._no_hits)
        for i, w in enumerate(widgets):
            self._mod_list.insertWidget(i, w)
        if self._sel_mod not in self._mod_entries:
            self._sel_mod = next(iter(self._mod_entries), None)
        self._apply_search()
        self._show_mod()

    def _apply_search(self) -> None:
        q = self.search.text()
        if self._mode == "methods":
            self._methods_proxy.setFilterFixedString(q.strip())
            return
        shares = rest = 0
        for mid, entry in self._mod_entries.items():
            row = self._mod_rows[mid]
            hit = bt.mod_matches(row, q)
            entry.setVisible(hit)
            if hit:
                shares += bool(row["shares"])
                rest += not row["shares"]
        if not hasattr(self, "_share_label"):
            return
        self._share_label.setVisible(shares > 0)
        self._share_label.findChild(QLabel).setText(f"Share code with another mod · {shares}")
        self._rest_label.setVisible(rest > 0)
        self._rest_label.findChild(QLabel).setText(
            f"Other matches · {rest}" if q.strip() else f"All other mods · {rest}" if shares else f"All mods · {rest}")
        self._no_hits.setText(f"Nothing matches “{q.strip()}”.")
        self._no_hits.setVisible(shares + rest == 0 and bool(self._mod_entries))

    def _select_mod(self, mid: str) -> None:
        if mid == self._sel_mod:
            return
        self._sel_mod = mid
        self._show_all_types = False
        log(f"[troubleshoot] mod selected: {mid}")
        self._show_mod()

    def jump_to_mod(self, mid: str) -> None:
        """A mod chip: Mod contents, that mod selected (the search cleared if it hides it)."""
        if mid not in self._mod_entries:
            log(f"[troubleshoot] jump to {mid}: not in Mod contents")
            return
        log(f"[troubleshoot] jump to mod {mid}")
        if self._mode != "mods":
            self._set_mode("mods", fade=False)
        if not bt.mod_matches(self._mod_rows[mid], self.search.text()):
            self.search.clear()
        self._sel_mod = mid
        self._show_all_types = False
        self.tabs.setCurrentIndex(1)  # the tab's own fade + sliding underline (painters.animate_tabs)
        self._show_mod()
        entry = self._mod_entries[mid]
        QTimer.singleShot(0, lambda: None if self._closed else self.mod_rail.ensureWidgetVisible(entry))  # after the relayout

    def jump_to_finding(self, fid: str) -> None:
        """"See what this caused in the last run": Log analyzer, that finding."""
        if self._view is not None and not self._view["live"] and self._entries and self._entries[0]["key"] == "live":
            self.run_picker.setCurrentIndex(0)  # tab 2 is about the live log: back to it first (-> _on_pick)
        f = self._finding(fid)
        if f is None:
            return
        log(f"[troubleshoot] jump to finding {fid}")
        if f["group"] == "harmless" and not self.harmless_box.isChecked():
            self.harmless_box.setChecked(True)
        self._sel_finding = fid
        self.tabs.setCurrentIndex(0)
        self._show_finding()
        entry = self._finding_entries.get(fid)
        if entry is not None:
            QTimer.singleShot(0, lambda: None if self._closed else self.finding_rail.ensureWidgetVisible(entry))

    def _show_mod(self) -> None:
        for mid, entry in self._mod_entries.items():
            entry.set_selected(mid == self._sel_mod)
        m = self._mod_rows.get(self._sel_mod)
        lay = self._set_detail(self.mod_detail)
        if m is None:
            lay.addWidget(_label("No mods installed in this profile." if not self._mod_rows else "", muted=True))
            lay.addStretch(1)
            return
        heading = painters.TerminalLabel(m["name"], rule="heading")
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        lay.addWidget(heading)
        ro = _Readout()
        files = QVBoxLayout()
        files.setSpacing(2)
        for rel, size in m["files"]:
            line = QHBoxLayout()
            line.setSpacing(6)
            name = _label(rel.rsplit("/", 1)[-1], role="ts-mono", wrap=False)
            name.setToolTip(rel)
            line.addWidget(name)
            line.addWidget(_label(bt.size_text(size), role="ts-small", muted=True, wrap=False))
            line.addStretch(1)
            files.addLayout(line)
        if not m["files"]:
            files.addWidget(_label("No code files (DLLs): this mod only adds assets or settings.", muted=True))
        ro.row("Files").addLayout(files, 1)
        ro.row("Namespaces").addWidget(_label(bt.namespaces_text(m), role="ts-mono"), 1)
        types = ro.row("Types")
        types.addWidget(_label(bt.types_text(m, self._show_all_types), role="ts-mono"), 1)
        if len(m["types"]) > bt.TYPES_SHOWN:
            types.addWidget(_link("Show fewer" if self._show_all_types else "Show all", self._toggle_types), 0,
                            Qt.AlignmentFlag.AlignTop)
        lay.addLayout(ro.grid)
        if m["shares"]:
            lay.addWidget(self._share_callout(m))
        else:
            lay.addWidget(_label("Shares no code with other installed mods.", muted=True))
        section = QVBoxLayout()
        section.setSpacing(SECTION_GAP)
        section.addWidget(painters.TerminalLabel("Game code it changes", rule="side"))
        section.addWidget(self._patches_for(m))
        lay.addLayout(section)
        lay.addStretch(1)

    def _toggle_types(self) -> None:
        self._show_all_types = not self._show_all_types
        painters.crossfade(self.mod_detail, self._show_mod, theme.MOTION_FAST)

    def _share_callout(self, m: dict) -> QFrame:
        box = QFrame()
        box.setProperty("role", "ts-callout")
        c = QVBoxLayout(box)
        c.setContentsMargins(10, 10, 10, 10)
        c.setSpacing(6)
        c.addWidget(painters.TerminalLabel("Shares code with", rule="side"))
        for share in m["shares"]:
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(_chip(share["name"], lambda o=share["id"]: self.jump_to_mod(o)))
            row.addWidget(_pill("certain"))
            row.addStretch(1)
            c.addLayout(row)
            c.addWidget(_label(bt.share_text(share)))
        c.addWidget(_label(bt.SHARE_ADVICE, muted=True))
        if self._res and self._res["run"] is not None:
            fid = bt.related_finding(self._res["findings"], m["id"], m["shares"][0]["id"])
            if fid:
                c.addWidget(_link("See what this caused in the last run", lambda: self.jump_to_finding(fid)), 0,
                            Qt.AlignmentFlag.AlignLeft)
        return box

    def _patches_for(self, m: dict) -> QWidget:
        if self._targets is None:
            return self._record_card()
        rows = bt.mod_patches(self._targets, m["id"], self._name)
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        if not rows:
            v.addWidget(_label("Changed no game methods in the recorded launch.", muted=True))
            return box
        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(2, 2)
        for col, head in enumerate(("Game method", "How", "Also changed by")):
            grid.addWidget(_label(head, role="ts-cell", muted=True), 0, col)
        for r, (target, how, also) in enumerate(rows, 1):
            cell = QFrame()
            cell.setProperty("role", "ts-value")
            cl = QHBoxLayout(cell)
            cl.setContentsMargins(0, 2, 6, 2)
            cl.addWidget(_link(target, lambda t=target: self.jump_to_method(t)), 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(cell, r, 0)
            grid.addWidget(_label(how, role="ts-cell"), r, 1)
            grid.addWidget(_label(also, role="ts-cell"), r, 2)
        v.addLayout(grid)
        v.addWidget(_label(self._patch_note + " " + MONO_NOTE, role="ts-small", muted=True))
        return box

    def _name(self, mod: str) -> str:
        """A package's display name; a patch VOLT couldn't match to a mod
        (bepinex_patchlog.UNMATCHED + its top namespace) says so."""
        if mod.startswith(pl.UNMATCHED):
            return f"{mod[len(pl.UNMATCHED):]} (not matched to a mod)"
        return self._mod_rows.get(mod, {}).get("name", mod)

    def _record_card(self) -> QWidget:
        """The mockup's "No diagnostic run yet" box: the record button (the
        profile's switch, shared with Settings > Troubleshooting), or, once
        on, "Will record on the next launch" + "Don't record"."""
        state = pl.load_state(self._root) if self._root else {"record": False, "pending": None}
        running = self._game_running()
        holder = QFrame()
        holder.setProperty("role", "first-run-card")
        h = QVBoxLayout(holder)
        h.setContentsMargins(14, 14, 14, 14)
        h.setSpacing(8)
        if state["record"] or state["pending"]:
            h.addWidget(_label(bt.PENDING_TITLE, role="first-run-title"))
            h.addWidget(_label(bt.pending_text(self._profile), muted=True))
            if not pl.cfg_path(self._root).is_file():
                h.addWidget(_label(pl.status_line(state, self._profile, cfg_exists=False, running=False),
                                   role="ts-small", muted=True))
            link = _link("Don't record", lambda: self._set_record(False))
            link.setEnabled(not running and not state["pending"])  # a recording in progress finishes on its own
            link.setToolTip(bt.RUNNING_TIP if running else "")
            h.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
        else:
            h.addWidget(_label(bt.NONE_TITLE, role="first-run-title"))
            h.addWidget(_label(bt.none_text(self._profile), muted=True))
            button = QPushButton(bt.RECORD_BUTTON)
            button.setProperty("variant", "accent-outline")
            button.setAutoDefault(False)
            button.setEnabled(not running and self._root is not None)
            button.setToolTip(bt.RUNNING_TIP if running else pl.RECORD_TOOLTIP)
            button.clicked.connect(lambda _=False: self._set_record(True))
            h.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            h.addWidget(_label(bt.RECORD_NOTE, role="ts-small", muted=True))
        return holder

    def _set_record(self, on: bool) -> None:
        if self._game_running():
            log("[troubleshoot] record patch details refused: the game is running")
        elif not pl.set_record(self._root, on, "Troubleshoot window"):
            self.patch_status.setText("Couldn't save the switch: is VOLT's folder read-only?")
            return
        self._apply_patch_state()
        if self._res is not None:
            painters.crossfade(self.mod_detail, self._show_mod, theme.MOTION_FAST)

    # ---- tab 2: game methods (dispatch C feeds the patch table) ----
    def set_patch_table(self, targets: dict | None, note: str = "", *, rows: dict | None = None,
                        recorded: str | None = None) -> None:
        """The recorded patch table {target: {package: {kind: n}}} and its note
        ("From the recorded launch at 19:23 today."); `rows` {target: [[kind
        index, package, patch method]]} gives each method's technical lines,
        `recorded` ("19:23 today") the status. None = no diagnostic run yet
        (Game methods disabled)."""
        self._targets, self._patch_note = targets, note
        self._patch_rows, self._patch_recorded = rows or {}, recorded
        self._methods_model.clear()
        for e in bt.method_entries(targets or {}):
            names = [self._name(n) for n in e["mods"]]
            item = QStandardItem(f"{e['target']}\n{len(e['mods'])} mod{'s' if len(e['mods']) != 1 else ''} · "
                                 f"{bt.kinds_text(e['kinds'])}")
            item.setData(e["target"], METHOD_ROLE)
            item.setData(" ".join([e["target"], *names, *e["mods"]]), FILTER_ROLE)
            self._methods_model.appendRow(item)
        log(f"[troubleshoot] patch table: {len(targets or {})} game methods")
        self._apply_patch_state()
        if self._res is not None:
            self._show_mod()

    def _apply_patch_state(self) -> None:
        have = self._targets is not None
        self.methods_seg.setEnabled(have)
        self.methods_seg.setToolTip("Every game method that mods change, and which mods change it" if have else
                                    "Needs a diagnostic run first: see \"Game code it changes\"")
        state = pl.load_state(self._root) if self._root and not have else {"record": False, "pending": None}
        self.patch_status.setText(bt.patch_status(len(self._targets) if have else None, self._patch_recorded,
                                                  bool(state["record"] or state["pending"])))
        if not have and self._mode == "methods":
            self._set_mode("mods", fade=False)

    def _set_mode(self, mode: str, fade: bool = True) -> None:
        if mode == self._mode or (mode == "methods" and self._targets is None):
            self.mods_seg.setChecked(self._mode == "mods")
            self.methods_seg.setChecked(self._mode == "methods")
            return

        def swap() -> None:
            self._mode = mode
            self.mods_seg.setChecked(mode == "mods")
            self.methods_seg.setChecked(mode == "methods")
            self.search.setPlaceholderText("Search a game method or a mod" if mode == "methods"
                                           else "Search a mod, a file, a namespace or a type")
            self.rail_stack.setCurrentIndex(1 if mode == "methods" else 0)
            self.detail_stack.setCurrentIndex(1 if mode == "methods" else 0)
            self._apply_search()

        log(f"[troubleshoot] Mod contents mode: {mode}")
        if fade:
            painters.crossfade(self._mods_body, swap, theme.MOTION_FAST)
        else:
            swap()

    def jump_to_method(self, target: str) -> None:
        self._set_mode("methods")
        for row in range(self._methods_model.rowCount()):
            item = self._methods_model.item(row)
            if item.data(METHOD_ROLE) == target:
                index = self._methods_proxy.mapFromSource(item.index())
                if not index.isValid():
                    self.search.clear()
                    index = self._methods_proxy.mapFromSource(item.index())
                self.methods_view.setCurrentIndex(index)
                self.methods_view.scrollTo(index)
                return

    def _show_method(self, index) -> None:
        lay = self._set_detail(self.method_detail)
        target = index.data(METHOD_ROLE) if index is not None and index.isValid() else None
        by_mod = (self._targets or {}).get(target)
        if not by_mod:
            lay.addWidget(_label("Pick a game method on the left.", muted=True))
            lay.addStretch(1)
            return
        lay.addWidget(painters.TerminalLabel("Game method", rule="heading"))
        lay.addWidget(_label(target, role="config-path"))
        ro = _Readout()
        row = ro.row("Changed by", flow=True)
        for mod in sorted(by_mod):
            row.addWidget(_chip(self._name(mod), lambda m=mod: self.jump_to_mod(m)))
        row = ro.row("Confidence")
        row.addWidget(_pill("possible"), 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(_label(bt.method_why(len(by_mod)), muted=True), 1)
        lay.addLayout(ro.grid)
        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)
        grid.setColumnStretch(0, 1)
        for col, head in enumerate(("Mod", "Prefix", "Postfix", "Transpiler", "Finalizer")):
            grid.addWidget(_label(head, role="ts-cell", muted=True), 0, col)
        for r, mod in enumerate(sorted(by_mod), 1):
            grid.addWidget(_label(self._name(mod), role="ts-cell"), r, 0)
            for col, kind in enumerate(bt.KINDS, 1):
                n = int(by_mod[mod].get(kind, 0))
                cell = _label(str(n) if n else "–", role="ts-cell", muted=not n)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(cell, r, col)
        lay.addLayout(grid)
        names = [self._name(m) for m in sorted(by_mod)]
        for title, text in (("What it means", bt.method_means(names)), ("What to try", bt.method_try(names, target))):
            section = QVBoxLayout()
            section.setSpacing(SECTION_GAP)
            section.addWidget(painters.TerminalLabel(title, rule="side"))
            blocks = TextBlocks()
            blocks.setText(text)
            section.addWidget(blocks)
            lay.addLayout(section)
        lay.addWidget(_label(MONO_NOTE, role="ts-small", muted=True))
        self._mtech_link = _link("", self._toggle_mtech)
        lay.addWidget(self._mtech_link, 0, Qt.AlignmentFlag.AlignLeft)
        tech = "\n\n".join(x for x in (pl.technical_text(target, self._patch_rows.get(target) or []),
                                        self._patch_note) if x)
        self._mtech_box = _well(_label(tech, role="ts-mono"))
        lay.addWidget(self._mtech_box)
        lay.addStretch(1)
        self._apply_mtech()

    def _apply_mtech(self) -> None:
        self._mtech_link.setText("▾ Hide technical details" if self._mtech_open else "▸ Technical details")
        self._mtech_box.setVisible(self._mtech_open)

    def _toggle_mtech(self) -> None:
        self._mtech_open = not self._mtech_open
        log(f"[troubleshoot] game method technical details {'shown' if self._mtech_open else 'hidden'}")
        painters.crossfade(self.method_detail, self._apply_mtech, theme.MOTION_FAST)

    # ---- lifecycle ----
    def done(self, result: int) -> None:
        self._closed = True
        self._poll.stop()
        log(f"[troubleshoot] window closed{' (a read was still running; its result is dropped)' if self._reading else ''}")
        super().done(result)
        self.deleteLater()  # a child of the screen: don't keep every closed window (and its results) until the screen goes
