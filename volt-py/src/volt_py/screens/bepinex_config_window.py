"""Edit Config window (THUNDERSTORE.md §7): the files under the open load
order's BepInEx/config/, browsed and edited in place. Built against the
signed-off design https://claude.ai/artifact/5WdEyKKwmrHpzvct1cqziY - the
rail + detail modal shape of the Help / Scan issues / Warnings windows
(16px padding, 10px gap), a 300px rail (search, sort, the file list) and
the detail pane (the file's path with Save / Revert / Delete / Open
externally, then either the parsed settings form or the raw text).

Game-agnostic: it takes a load order's name and its BepInEx folder, nothing
else. `BepInExConfigWindow(name, bepinex_dir, parent=self).exec()`.

What the detail pane shows, per file (bepinex_config.py decides):
  - a .cfg with BepInEx's setting metadata: one block per [Section], one
    row per entry - key, description, "Setting type · Default value", the
    Acceptable values / range line, and the control the type calls for
    (drop-down for an enum / Toggle / Boolean, check boxes for a [Flags]
    enum, an editable KeyCode drop-down for a KeyboardShortcut - typed
    combos like "Z + LeftAlt" stay as typed - a number
    field, a color swatch + RRGGBBAA field, a multi-line box for a long
    String, a text field for the rest);
  - a .cfg without metadata (descriptions turned off): the same form with
    just key + text field per entry;
  - anything else that is UTF-8 text (.json / .yml / .txt, a .cfg with no
    entries): a raw text box under a banner saying why;
  - a file that isn't text: a message, Save off (Open externally still works).
Save writes only the changed `Key = Value` lines (bepinex_config.
ConfigDocument.set_value), or the whole text for a raw file, then re-reads
the file. Switching files / closing with unsaved edits asks first.

The pinned toolbar over the form (the same design's ConfigJump artboard;
THUNDERSTORE.md §7's QoL pass) - shown only while a parsed form is:
  - section jump, rebuilt per file: 2..5 sections = one chip each ("1 -
    General" -> "General", the header as tooltip, elided at 130px), 6+ = a
    "Sections (N)" button opening a filterable popup list; a click scrolls
    the form (150ms ease) so that section's heading is at the top;
  - search over setting names + descriptions (case-insensitive substring,
    150ms debounce): Highlight mode keeps the whole form, tints the matches
    (the current one stronger), dims the rest, paints the matched text and
    steps with the up / down buttons (wrapping) or Enter; Filter mode (the
    toggle) hides non-matching entries and emptied sections. Chips / popup
    rows of sections with no matches dim in Filter mode. Ctrl+F focuses the
    field, Esc in it clears a query (an empty one lets Esc close as before).
  Nothing is rebuilt per keystroke: the form's rows (each a card of its
  own) toggle visibility / a style property / their label text, and only
  the rows whose state changed are touched - Therzie.Warfare.cfg (1398
  entries, 182 sections) is the stress case.
"""

import re
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRegularExpression,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPainter, QRegularExpressionValidator, QShortcut
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from volt_py import bepinex_config as bc
from volt_py import theme
from volt_py.applog import log

WINDOW_SIZE = (1000, 680)  # the mockup's artboard
RAIL_WIDTH = 300
FIELD_WIDTH = 260  # text / drop-down controls
NUMBER_WIDTH = 100
COLOR_WIDTH = 140
LONG_TEXT_HEIGHT = (44, 180)  # collapsed / "Show more"
FLAG_COLUMNS = 4
# The form's entry cards (the ConfigJump artboard): 1px border + 6px 8px
# padding, 6px between the rows of a section, 14px between sections.
ROW_MARGINS = (9, 7, 9, 7)
SECTION_GAP = 6
# The toolbar: 8px between the jump control / wrapped rows and the search
# group, 6px between chips, chips elided at 130px, the search group never
# narrower than 280px (it wraps to its own row instead).
TOOLBAR_GAP = 8
CHIP_GAP = 6
CHIP_MAX_WIDTH = 130
SEARCH_MIN_WIDTH = 280
POPUP_WIDTH = 270
POPUP_LIST_HEIGHT = 270
POPUP_SHADOW = (24, 16, 24, 32)  # room around the popup frame for its 0 8px 24px shadow
SEARCH_DEBOUNCE_MS = 150
SCROLL_MS = 150
SCROLL_LEAD = 4  # px above the target the scroll lands at (the mockup's offsetTop - 4)

NO_FILES = "No config files."
NEVER_RUN = ("No config files yet.\n\nBepInEx writes each mod's default config file the first time "
             "this load order is run.")
NO_TEXT_FILES = "Only non-text files here. \"Show all files\" lists them."
NO_MATCHES = "No matches"
PICK_A_FILE = "Select a config file on the left."
RAW_BANNER = "No BepInEx setting metadata found in this file - showing raw text instead of a parsed form."
BINARY_BANNER = "This file isn't text (or isn't UTF-8), so it can't be shown here. Open externally to view it."
NO_SETTINGS_MATCH = 'No settings match "{query}" in this file.'
NO_SECTIONS_MATCH = "No sections match."
FILTER_TIP = "Off: highlight matches and step through them. On: hide settings that do not match."

_INT_RE = QRegularExpression(r"-?\d*")
_FLOAT_RE = QRegularExpression(r"-?\d*\.?\d*(?:[eE][-+]?\d*)?")
_HEX_RE = QRegularExpression(r"[0-9A-Fa-f]{0,8}")


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _label(text: str, role: str, *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("role", role)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _link(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", "link")
    button.setProperty("small", True)
    button.setAutoDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("configDivider")
    line.setFixedHeight(1)
    return line


def _transparent(scroll: QScrollArea) -> None:
    scroll.viewport().setAutoFillBackground(False)
    scroll.widget().setAutoFillBackground(False)


class _ElidedLabel(QLabel):
    """One line, elided to its width, the full text as the tooltip."""

    def __init__(self, role: str) -> None:
        super().__init__()
        self.setProperty("role", role)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self._full = ""

    def set_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = self.contentsRect().width()
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, width)))


class _Wash(QWidget):
    """A 50% --panel wash a row paints over itself to dim as a non-match
    (CSS `opacity: 0.5` over the pane's flat --panel background gives
    exactly this blend; QSS has no opacity, and a per-child alpha color
    would miss check-box indicators and the color swatch). Mouse events
    pass through; it isn't in the row's layout, just kept at its size."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._color = QColor(theme.PANEL)
        self._color.setAlphaF(0.5)
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color)
        painter.end()


class _EntryRow(QFrame):
    """One entry's card: a QFrame (variant config-row) owning the row's
    zero-margin-plus-card-padding QVBoxLayout - a widget, never a bare
    nested layout (the v0.4.24 rule, see _build_row). The search sets
    `hit` ("" / match / current, the QSS tint), the dim wash and the
    highlighted label text; each setter is a no-op when nothing changed."""

    def __init__(self, entry: bc.Entry) -> None:
        super().__init__()
        self.setProperty("variant", "config-row")
        self.setProperty("hit", "")
        self.entry = entry
        self.key_label: QLabel | None = None
        self.desc_label: QLabel | None = None
        self.match = False
        self.state = ""
        self.dim = False
        self.hidden = False
        self._highlight_key: str | None = None
        self._wash = _Wash(self)

    def finish(self) -> None:
        self._wash.raise_()  # above the content the layout added after it

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._wash.setGeometry(self.rect())

    def set_state(self, state: str) -> bool:
        if state == self.state:
            return False
        self.state = state
        self.setProperty("hit", state)
        _repolish(self)
        return True

    def set_dim(self, dim: bool) -> None:
        if dim != self.dim:
            self.dim = dim
            self._wash.setVisible(dim)

    def set_hidden(self, hidden: bool) -> None:
        if hidden != self.hidden:
            self.hidden = hidden
            self.setVisible(not hidden)

    def set_highlight(self, pattern: re.Pattern | None) -> None:
        key = pattern.pattern if pattern is not None else None
        if key == self._highlight_key:
            return
        self._highlight_key = key
        for label, text in ((self.key_label, self.entry.key), (self.desc_label, self.entry.description)):
            if label is None:
                continue
            if pattern is None:
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setText(text)
            else:
                label.setTextFormat(Qt.TextFormat.RichText)
                label.setText(bc.highlight_html(text, pattern))


class _Section(QWidget):
    """One [Section] block: the heading (a rule under it) and its rows, as
    a widget so Filter mode can hide an emptied section outright."""

    def __init__(self, header: str) -> None:
        super().__init__()
        self.header = header
        self.rows: list[_EntryRow] = []
        self.any_match = False
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(SECTION_GAP)
        self.heading: QLabel | None = None
        if header:
            self.heading = _label(header, "config-section")
            self.layout_.addWidget(self.heading)

    def add_row(self, row: _EntryRow) -> None:
        self.rows.append(row)
        self.layout_.addWidget(row)


class _ToolbarLayout(QLayout):
    """The pinned toolbar's flow - the artboard's `display: flex; flex-wrap:
    wrap; gap: 8px` with the chips in their own 6px-gap wrapping group and
    the search group `flex: 1 1 280px`: the leading items (chips, or the
    Sections button) at their size hints, then the last item filling the
    rest of the row; when the leading items + 280px don't fit, the leading
    items wrap among themselves and the last item takes a full-width row of
    its own. Height-for-width, so the detail column grows with the rows."""

    def __init__(self, fill_min_width: int = SEARCH_MIN_WIDTH, lead_gap: int = CHIP_GAP,
                 gap: int = TOOLBAR_GAP) -> None:
        super().__init__()
        self._items: list = []
        self.fill_min_width = fill_min_width
        self.lead_gap = lead_gap
        self.gap = gap
        self.setContentsMargins(0, 0, 0, 0)

    # ---- item storage ----
    def addItem(self, item) -> None:
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self._items.insert(index, QWidgetItem(widget))
        self.invalidate()

    def removeWidget(self, widget: QWidget) -> None:
        self._items = [item for item in self._items if item.widget() != widget]
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    # ---- sizing ----
    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self) -> QSize:
        lead, fill = self._visible()
        width = sum(hint.width() for _, hint in lead) + self.lead_gap * max(0, len(lead) - 1)
        if fill is not None:
            width += (self.gap if lead else 0) + self.fill_min_width
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        lead, fill = self._visible()
        width = max([hint.width() for _, hint in lead] + [self.fill_min_width if fill else 0])
        return QSize(width, self.heightForWidth(width))

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    def _visible(self):
        """(the leading items + hints, the fill item + hint or None)."""
        if not self._items:
            return [], None
        lead = [(item, item.sizeHint()) for item in self._items[:-1] if not item.isEmpty()]
        last = self._items[-1]
        return lead, (None if last.isEmpty() else (last, last.sizeHint()))

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        lead, fill = self._visible()
        x0, y0, width = rect.x(), rect.y(), rect.width()
        lead_width = sum(hint.width() for _, hint in lead) + self.lead_gap * max(0, len(lead) - 1)
        fill_height = fill[1].height() if fill is not None else 0
        if fill is not None and (not lead or lead_width + self.gap + self.fill_min_width <= width):
            # One row: leading items, then the fill item over the rest.
            row_height = max([fill_height] + [hint.height() for _, hint in lead])
            if apply:
                x = x0
                for item, hint in lead:
                    item.setGeometry(QRect(x, y0 + (row_height - hint.height()) // 2, hint.width(), hint.height()))
                    x += hint.width() + self.lead_gap
                fx = x0 + lead_width + self.gap if lead else x0
                fill[0].setGeometry(QRect(fx, y0 + (row_height - fill_height) // 2, width - (fx - x0), fill_height))
            return row_height
        # Wrapped: the leading items flow in rows of their own, the fill
        # item on a full-width row under them.
        y = y0
        row: list = []
        row_width = row_height = 0

        def place() -> None:
            x = x0
            for item, hint in row:
                if apply:
                    item.setGeometry(QRect(x, y + (row_height - hint.height()) // 2, hint.width(), hint.height()))
                x += hint.width() + self.lead_gap

        for item, hint in lead:
            needed = hint.width() if not row else row_width + self.lead_gap + hint.width()
            if row and needed > width:
                place()
                y += row_height + self.lead_gap
                row, row_width, row_height = [], 0, 0
                needed = hint.width()
            row.append((item, hint))
            row_width = needed
            row_height = max(row_height, hint.height())
        if row:
            place()
            y += row_height
        if fill is not None:
            if lead:
                y += self.gap
            if apply:
                fill[0].setGeometry(QRect(x0, y, width, fill_height))
            y += fill_height
        return y - y0


class _SectionsPopup(QWidget):
    """The "Sections (N)" popup: a Qt.Popup window (closes on an outside
    click / Esc) holding a 270px --panel-2 frame with a filter field and
    the scrolling list of section headers; a drop shadow around the frame,
    so the window is translucent with room for it. `on_pick(index)` is
    called with the picked section's index after the popup closes."""

    def __init__(self, parent: QWidget, on_pick, on_hide) -> None:
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._on_pick = on_pick
        self._on_hide = on_hide
        self._rows: list[QPushButton] = []
        self._headers: list[str] = []
        self._outer = outer = QVBoxLayout(self)
        outer.setContentsMargins(*POPUP_SHADOW)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)  # follows its rows, like a menu
        self.frame = QFrame()
        self.frame.setObjectName("configSectionsPopup")
        self.frame.setFixedWidth(POPUP_WIDTH)
        shadow = QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 115))  # rgba(0,0,0,0.45)
        self.frame.setGraphicsEffect(shadow)
        outer.addWidget(self.frame)
        column = QVBoxLayout(self.frame)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter sections…")
        self.filter.textChanged.connect(lambda _t: self._apply_filter())
        self.filter.returnPressed.connect(lambda: self._pick_first())
        column.addWidget(self.filter)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("configSectionsList")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self.scroll.setMaximumHeight(POPUP_LIST_HEIGHT)
        self.inner = QWidget()
        self.list_layout = QVBoxLayout(self.inner)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(2)
        self.empty = _label(NO_SECTIONS_MATCH, "config-counter")  # muted 12px
        self.empty.setContentsMargins(10, 6, 10, 6)
        self.list_layout.addWidget(self.empty)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.inner)
        _transparent(self.scroll)
        column.addWidget(self.scroll)

    def set_sections(self, headers: list[str]) -> None:
        for row in self._rows:
            self.list_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._rows = []
        text_width = POPUP_WIDTH - 2 * 8 - 2 * 10 - 12  # frame padding, row padding, the scrollbar
        for i, header in enumerate(headers):
            row = QPushButton(self.fontMetrics().elidedText(header, Qt.TextElideMode.ElideRight, text_width))
            row.setProperty("variant", "config-entry")
            row.setProperty("popup", True)
            row.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            row.setAutoDefault(False)
            row.setToolTip(header)
            row.clicked.connect(lambda _=False, i=i: self._pick(i))
            self.list_layout.insertWidget(i, row)
            self._rows.append(row)
        self._headers = list(headers)
        self.filter.setText("")
        self._apply_filter()

    def set_dim(self, dim: list[bool]) -> None:
        for row, d in zip(self._rows, dim):
            if bool(row.property("dim")) != d:
                row.setProperty("dim", d)
                _repolish(row)

    def open_below(self, button: QWidget) -> None:
        self.filter.setText("")
        self._outer.activate()  # size it now (SetFixedSize), before the first show
        left, top, right, bottom = POPUP_SHADOW
        # The frame's top-left goes 2px under the button's left edge; the
        # window is offset by the shadow room. Kept on the screen.
        frame_pos = button.mapToGlobal(QPoint(0, button.height() + 2))
        screen = button.screen()
        if screen is not None:
            area = screen.availableGeometry()
            frame_height = self.height() - top - bottom
            frame_pos.setX(max(area.left(), min(frame_pos.x(), area.right() - POPUP_WIDTH + 1)))
            frame_pos.setY(max(area.top(), min(frame_pos.y(), area.bottom() - frame_height + 1)))
        self.move(frame_pos - QPoint(left, top))
        self.show()
        self.filter.setFocus()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._on_hide()

    def _apply_filter(self) -> None:
        shown = set(bc.filter_sections(self._headers, self.filter.text())) if self._rows else set()
        visible = 0
        for header, row in zip(self._headers, self._rows):
            on = header in shown
            row.setVisible(on)
            visible += on
        self.empty.setVisible(not visible)

    def _pick(self, index: int) -> None:
        self.hide()
        self._on_pick(index)

    def _pick_first(self) -> None:
        for i, row in enumerate(self._rows):
            if not row.isHidden():
                self._pick(i)
                return


class BepInExConfigWindow(QDialog):
    def __init__(self, load_order_name: str, bepinex_dir: Path, parent: QWidget | None = None,
                 *, query: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("editConfig")
        self.setWindowTitle("Edit Config")
        self.setModal(True)
        self._bepinex_dir = Path(bepinex_dir)
        self._files_all: list[bc.ConfigFile] = []
        self._shown: list[bc.ConfigFile] = []
        self._buttons: list[QPushButton] = []
        self._current: bc.ConfigFile | None = None
        self._doc: bc.ConfigDocument | None = None  # the parsed .cfg, when the form is showing
        self._text: str | None = None  # the file's text as read (raw mode: the Revert baseline)
        self._getters: list = []  # (entry, current-value getter) per form control
        # the form's structure, for the toolbar: sections / rows in file
        # order, the current search's hits, the chips / popup rows per section
        self._sections: list[_Section] = []
        self._rows: list[_EntryRow] = []
        self._hits: list[_EntryRow] = []
        self._hit_index = 0
        self._form_gen = 0  # bumped per form build: a deferred scroll for an older form is dropped
        self._jump_widgets: list[QPushButton] = []
        self._chips: list[QPushButton] = []
        self._popup: _SectionsPopup | None = None
        self._applied_query = ""  # the query the form's current hit list is for

        layout = QVBoxLayout(self)  # .modal: padding 16px, gap 10px
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(f"Edit Config — {load_order_name}")
        title.setProperty("role", "modal-title")
        header.addWidget(title, 1)
        self.close_button = QPushButton("Close")
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(lambda: self.reject())
        header.addWidget(self.close_button)
        layout.addLayout(header)

        body = QHBoxLayout()
        body.setSpacing(8)
        body.addWidget(self._build_rail())
        body.addWidget(self._build_detail(), 1)
        layout.addLayout(body, 1)

        width, height = WINDOW_SIZE
        if parent is not None:
            bounds = parent.window().size()
            width, height = min(width, bounds.width() - 32), min(height, bounds.height() - 32)
        self.resize(width, height)

        # Ctrl+F: the in-file search while a form is showing, else the rail's file search.
        QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self).activated.connect(lambda: self._focus_search())

        self.reload_files()
        if query and any(bc.file_matches(f, query) for f in self._files_all):
            self.search.setText(query)  # a hint from the caller, only when it finds something
        self._show_file(None)
        self.close_button.setFocus()

    # ---- rail ----
    def _build_rail(self) -> QFrame:
        rail = QFrame()
        rail.setObjectName("configRail")
        rail.setFixedWidth(RAIL_WIDTH)
        column = QVBoxLayout(rail)
        column.setContentsMargins(10, 10, 10, 10)
        column.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search config files…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _text: self._rebuild_list())
        column.addWidget(self.search)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.sort_combo = QComboBox()
        for key in bc.SORT_KEYS:
            self.sort_combo.addItem(bc.SORT_LABELS[key], key)
        self.sort_combo.currentIndexChanged.connect(lambda _i: self._rebuild_list())
        row.addWidget(self.sort_combo, 1)
        self.all_files = QCheckBox("Show all files")
        self.all_files.setToolTip("Also list the files that aren't config text (.dat saves, blueprint "
                                  "exports...). Shown as raw text when they are text at all.")
        self.all_files.toggled.connect(lambda _on: self._rebuild_list())
        row.addWidget(self.all_files)
        column.addLayout(row)
        column.addWidget(_divider())
        self._rail_scroll = QScrollArea()
        self._rail_scroll.setObjectName("configRailList")
        self._rail_scroll.setWidgetResizable(True)
        self._rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_inner = QWidget()
        self._rail_layout = QVBoxLayout(self._rail_inner)
        self._rail_layout.setContentsMargins(0, 0, 0, 0)
        self._rail_layout.setSpacing(2)
        self._rail_empty = _label("", "config-empty", wrap=True)
        self._rail_empty.setContentsMargins(10, 6, 10, 6)
        self._rail_layout.addWidget(self._rail_empty)
        self._rail_layout.addStretch(1)
        self._rail_scroll.setWidget(self._rail_inner)
        _transparent(self._rail_scroll)
        column.addWidget(self._rail_scroll, 1)
        return rail

    def reload_files(self) -> None:
        self._files_all = bc.list_config_files(self._bepinex_dir, all_files=True)
        log(f"edit config: {len(self._files_all)} files under {bc.config_dir(self._bepinex_dir)}")
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        for button in self._buttons:
            self._rail_layout.removeWidget(button)
            button.hide()  # gone now, not when deleteLater gets around to it
            button.deleteLater()
        self._buttons = []
        files = self._files_all if self.all_files.isChecked() else [f for f in self._files_all if f.is_text]
        query = self.search.text()
        self._shown = bc.sort_files([f for f in files if bc.file_matches(f, query)], self.sort_combo.currentData())
        # Long nested paths are elided in the middle (the folder start and the
        # file name both stay readable); the tooltip has the whole path. Ignored
        # horizontally so a long name never widens the rail past its 300px.
        text_width = RAIL_WIDTH - 2 * 10 - 2 * 10 - 12  # rail padding, row padding, the scrollbar
        for i, f in enumerate(self._shown):
            button = QPushButton(self.fontMetrics().elidedText(f.rel, Qt.TextElideMode.ElideMiddle, text_width))
            button.setProperty("variant", "config-entry")
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            button.setAutoDefault(False)
            button.setToolTip(f"{f.path}\n{f.size:,} bytes")
            button.setProperty("selected", self._current is not None and f.path == self._current.path)
            button.clicked.connect(lambda _=False, f=f: self._pick(f))
            self._rail_layout.insertWidget(1 + i, button)
            self._buttons.append(button)
        empty = (NO_FILES if not self._files_all else NO_MATCHES if query.strip()
                 else NO_TEXT_FILES if not files else "")
        self._rail_empty.setText(empty)
        self._rail_empty.setVisible(not self._shown)

    def _mark_selected(self) -> None:
        for f, button in zip(self._shown, self._buttons):
            selected = self._current is not None and f.path == self._current.path
            if button.property("selected") != selected:
                button.setProperty("selected", selected)
                _repolish(button)

    # ---- detail ----
    def _build_detail(self) -> QFrame:
        detail = QFrame()
        detail.setObjectName("configDetail")
        column = QVBoxLayout(detail)
        column.setContentsMargins(16, 14, 16, 14)
        column.setSpacing(10)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.path_label = _ElidedLabel("config-path")
        toolbar.addWidget(self.path_label, 1)
        self.save_button = QPushButton("Save")
        self.save_button.setProperty("variant", "primary")
        self.revert_button = QPushButton("Revert")
        self.delete_button = QPushButton("Delete")
        self.open_button = QPushButton("Open externally")
        self.open_button.setProperty("variant", "link")
        for button in (self.save_button, self.revert_button, self.delete_button, self.open_button):
            button.setAutoDefault(False)
            toolbar.addWidget(button)
        self.save_button.clicked.connect(lambda: self._save())
        self.revert_button.clicked.connect(lambda: self._revert())
        self.delete_button.clicked.connect(lambda: self._delete())
        self.open_button.clicked.connect(lambda: self._open_externally())
        column.addLayout(toolbar)
        column.addWidget(_divider())
        self.jump_bar = self._build_toolbar()  # pinned: a sibling of the scroll area, not inside it
        column.addWidget(self.jump_bar)

        self.placeholder = _label(PICK_A_FILE, "config-empty", wrap=True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.placeholder, 1)

        self.form_scroll = QScrollArea()
        self.form_scroll.setObjectName("configForm")
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.form_scroll.setWidget(QWidget())
        _transparent(self.form_scroll)
        column.addWidget(self.form_scroll, 1)
        # One animation on the scroll area's own bar (the bar outlives the
        # forms); stopped before every restart, so a second jump mid-flight
        # just retargets.
        self._scroll_anim = QPropertyAnimation(self.form_scroll.verticalScrollBar(), b"value", self)
        self._scroll_anim.setDuration(SCROLL_MS)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.raw_box = QWidget()
        raw = QVBoxLayout(self.raw_box)
        raw.setContentsMargins(0, 0, 0, 0)
        raw.setSpacing(10)
        self.banner = _label(RAW_BANNER, "config-banner", wrap=True)
        raw.addWidget(self.banner)
        self.raw_edit = QPlainTextEdit()
        self.raw_edit.setProperty("mono", True)
        self.raw_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.raw_edit.textChanged.connect(lambda: self._refresh_actions())
        raw.addWidget(self.raw_edit, 1)
        column.addWidget(self.raw_box, 1)
        return detail

    # ---- the pinned toolbar: section jump + in-file search ----
    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        self._toolbar_layout = _ToolbarLayout()
        bar.setLayout(self._toolbar_layout)
        # The search group: the input-look box (a bare line edit, the
        # counter, up / down, clear) and the Filter toggle. Added last: the
        # layout's fill item; the jump control is inserted before it.
        group = QWidget()
        row = QHBoxLayout(group)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.search_box = QFrame()
        self.search_box.setObjectName("configSearchBox")
        self.search_box.setProperty("fieldFocus", False)  # not "focus": QWidget's read-only Q_PROPERTY (hasFocus) - setProperty on it is a no-op
        inner = QHBoxLayout(self.search_box)
        inner.setContentsMargins(10, 2, 6, 2)
        inner.setSpacing(4)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("configSearchEdit")
        self.search_edit.setPlaceholderText("Search names and descriptions…")
        self.search_edit.setClearButtonEnabled(False)  # the x mini button is the clear
        self.search_edit.installEventFilter(self)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start())
        self.search_edit.returnPressed.connect(lambda: self._search_return())
        inner.addWidget(self.search_edit, 1)
        self.counter = _label("", "config-counter")
        self.counter.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        inner.addWidget(self.counter)
        self.prev_button = self._mini("↑", "Previous match", lambda: self._step(-1))
        self.next_button = self._mini("↓", "Next match", lambda: self._step(1))
        self.clear_button = self._mini("×", "Clear search", lambda: self._clear_query())
        for button in (self.prev_button, self.next_button, self.clear_button):
            inner.addWidget(button)
            button.setVisible(False)
        self.counter.setVisible(False)
        row.addWidget(self.search_box, 1)
        self.filter_button = QPushButton("Filter")
        self.filter_button.setProperty("variant", "config-filter")
        self.filter_button.setCheckable(True)
        self.filter_button.setAutoDefault(False)
        self.filter_button.setToolTip(FILTER_TIP)
        self.filter_button.toggled.connect(lambda _on: self._mode_toggled())
        row.addWidget(self.filter_button)
        self._toolbar_layout.addWidget(group)
        # The query settles 150ms after the last keystroke before the form
        # is touched (Warfare: 1398 rows to re-check per change).
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(lambda: self._apply_search())
        bar.setVisible(False)
        return bar

    @staticmethod
    def _mini(text: str, tip: str, on_click) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "config-mini")
        button.setAutoDefault(False)
        button.setToolTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # keep the caret in the field
        button.clicked.connect(lambda _=False: on_click())
        return button

    def _rebuild_jump(self) -> None:
        """The jump control for the form showing: chips for 2..CHIP_MAX
        sections, the Sections (N) button for more, nothing otherwise."""
        for widget in self._jump_widgets:
            self._toolbar_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
        self._jump_widgets = []
        self._chips = []
        headers = [section.header for section in self._sections]
        mode = bc.jump_mode(len(headers))
        if mode == "chips":
            text_width = CHIP_MAX_WIDTH - 2 * 12 - 2  # the button's padding + border
            for i, header in enumerate(headers):
                chip = QPushButton(self.fontMetrics().elidedText(bc.section_label(header),
                                                                 Qt.TextElideMode.ElideRight, text_width))
                chip.setProperty("variant", "config-chip")
                chip.setProperty("dim", False)
                chip.setMaximumWidth(CHIP_MAX_WIDTH)
                chip.setAutoDefault(False)
                chip.setToolTip(header)
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.clicked.connect(lambda _=False, i=i: self._jump_to_section(i))
                self._toolbar_layout.insertWidget(i, chip)
                self._jump_widgets.append(chip)
                self._chips.append(chip)
        elif mode == "list":
            button = QPushButton(f"Sections ({len(headers)}) ▾")
            button.setProperty("variant", "config-sections")
            button.setProperty("open", False)
            button.setAutoDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False: self._open_sections_popup())
            self._toolbar_layout.insertWidget(0, button)
            self._jump_widgets.append(button)
            self.sections_button = button
            if self._popup is None:
                self._popup = _SectionsPopup(self, self._jump_to_section, self._popup_hidden)
            self._popup.set_sections(headers)

    def _open_sections_popup(self) -> None:
        if self._popup is None or not self._jump_widgets:
            return
        button = self._jump_widgets[0]
        button.setProperty("open", True)
        _repolish(button)
        self._popup.open_below(button)

    def _popup_hidden(self) -> None:
        if self._jump_widgets and self._jump_widgets[0].property("open"):
            self._jump_widgets[0].setProperty("open", False)
            _repolish(self._jump_widgets[0])

    def _jump_to_section(self, index: int) -> None:
        if 0 <= index < len(self._sections):
            log(f"edit config: jump to section [{self._sections[index].header}]")
            self._scroll_to(self._sections[index])

    def _scroll_to(self, widget: QWidget) -> None:
        """Scrolls the form so `widget` (a section or a row) sits at the
        top, animated. Deferred one event-loop turn so a layout pass from
        just-hidden / shown rows has settled the positions and the bar's
        range first; a form rebuilt meanwhile drops the jump."""
        gen = self._form_gen

        def go() -> None:
            if gen != self._form_gen or self._doc is None or widget.isHidden():
                return
            bar = self.form_scroll.verticalScrollBar()
            y = widget.mapTo(self.form_scroll.widget(), QPoint(0, 0)).y() - SCROLL_LEAD
            y = max(0, min(y, bar.maximum()))
            self._scroll_anim.stop()
            if not theme.animations_enabled():  # Settings > Animations: Off = a plain jump
                bar.setValue(y)
                return
            self._scroll_anim.setStartValue(bar.value())
            self._scroll_anim.setEndValue(y)
            self._scroll_anim.start()

        QTimer.singleShot(0, go)

    def _set_query(self, text: str) -> None:
        """Sets the field without the debounce (the caller applies)."""
        self._search_timer.stop()
        self.search_edit.blockSignals(True)
        self.search_edit.setText(text)
        self.search_edit.blockSignals(False)

    def _clear_query(self) -> None:
        self._set_query("")
        self._hit_index = 0
        self._apply_search(scroll=False)
        self.search_edit.setFocus()

    def _mode_toggled(self) -> None:
        self._hit_index = 0
        self._apply_search()

    def _search_return(self) -> None:
        if self._search_timer.isActive():  # Enter right after typing: settle now
            self._search_timer.stop()
            self._apply_search()
        else:
            self._step(1)

    def _focus_search(self) -> None:
        field = self.search_edit if self.jump_bar.isVisible() else self.search
        field.setFocus()
        field.selectAll()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.search_edit:
            kind = event.type()
            if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.search_edit.text():
                self._clear_query()  # an empty field leaves Esc to the dialog (Close)
                return True
            if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self.search_box.setProperty("fieldFocus", kind == QEvent.Type.FocusIn)
                _repolish(self.search_box)
        return super().eventFilter(obj, event)

    def _apply_search(self, *, scroll: bool = True) -> None:
        """Re-marks the form for the field's query: each row's match flag,
        its card state / dim wash / visibility / highlighted labels, each
        section's visibility and chip / popup-row dim, the counter and the
        buttons. Only rows whose state changed are touched; nothing is
        rebuilt. Highlight mode scrolls to the current hit (`scroll`)."""
        query = self.search_edit.text()
        pattern = bc.search_pattern(query)
        if query.strip() != self._applied_query.strip():
            self._hit_index = 0
        self._applied_query = query
        filtering = pattern is not None and self.filter_button.isChecked()
        hits: list[_EntryRow] = []
        for row in self._rows:
            row.match = pattern is not None and bc.entry_matches(row.entry, pattern)
            if row.match:
                hits.append(row)
        self._hits = hits
        self._hit_index = min(self._hit_index, len(hits) - 1) if hits else 0
        current = hits[self._hit_index] if hits and not filtering else None
        for row in self._rows:
            state = "" if pattern is None or filtering else "current" if row is current else "match" if row.match else ""
            row.set_state(state)
            row.set_dim(pattern is not None and not filtering and not row.match)
            row.set_hidden(filtering and not row.match)
            row.set_highlight(pattern if row.match else None)
        dims: list[bool] = []
        for section in self._sections:
            section.any_match = any(row.match for row in section.rows)
            section.setVisible(not filtering or section.any_match)
            dims.append(filtering and not section.any_match)
        for chip, dim in zip(self._chips, dims):
            if bool(chip.property("dim")) != dim:
                chip.setProperty("dim", dim)
                _repolish(chip)
        if self._popup is not None and bc.jump_mode(len(self._sections)) == "list":
            self._popup.set_dim(dims)
        if hasattr(self, "no_match"):
            self.no_match.setText(NO_SETTINGS_MATCH.format(query=query.strip()))
            self.no_match.setVisible(filtering and not hits)
        self._update_search_ui(pattern is not None, filtering)
        if pattern is not None:
            log(f"edit config: search {query.strip()!r} ({'filter' if filtering else 'highlight'}): "
                f"{len(hits)} of {len(self._rows)} entries")
        if scroll and current is not None:
            self._scroll_to(current)

    def _update_search_ui(self, has_query: bool, filtering: bool) -> None:
        n = len(self._hits)
        self.counter.setVisible(has_query)
        self.clear_button.setVisible(has_query)
        step = has_query and not filtering and n > 0
        self.prev_button.setVisible(step)
        self.next_button.setVisible(step)
        if has_query:
            self.counter.setText("No matches" if not n else f"{n} shown" if filtering else f"{self._hit_index + 1} / {n}")

    def _step(self, delta: int) -> None:
        """Up / down: the previous / next hit, wrapping (Highlight mode)."""
        if not self._hits or self.filter_button.isChecked():
            return
        old = self._hits[self._hit_index]
        self._hit_index = (self._hit_index + delta) % len(self._hits)
        new = self._hits[self._hit_index]
        old.set_state("match")
        new.set_state("current")
        self._update_search_ui(True, False)
        self._scroll_to(new)

    def _pick(self, f: bc.ConfigFile) -> None:
        if self._current is not None and f.path == self._current.path:
            return
        if not self._confirm_discard():
            return
        self._show_file(f)

    def _show_file(self, f: bc.ConfigFile | None) -> None:
        """Loads `f` into the detail pane (None: nothing selected). A
        re-read of the file already showing (Save / Revert) keeps the
        search query and the scroll position; another file starts clean
        (the Filter toggle keeps its state either way)."""
        same = f is not None and self._current is not None and f.path == self._current.path and self._doc is not None
        scroll_value = self.form_scroll.verticalScrollBar().value() if same else 0
        self._current = f
        self._doc = None
        self._text = None
        self._getters = []
        self._sections = []
        self._rows = []
        self._hits = []
        if not same:
            self._set_query("")
            self._hit_index = 0
        self.path_label.set_text(f"BepInEx/config/{f.rel}" if f else "")
        self.form_scroll.setVisible(False)
        self.raw_box.setVisible(False)
        self.placeholder.setVisible(f is None)
        if f is None:
            self.placeholder.setText(NEVER_RUN if not self._files_all else PICK_A_FILE)
        else:
            try:
                self._text = bc.read_text(f.path)
            except OSError as err:
                log(f"edit config: read {f.path} failed: {err}")
                self._warn("Couldn't read the file", f"{f.rel}\n\n{err}")
                self._text = None
            if self._text is None:
                self.raw_edit.setPlainText("")
                self.raw_edit.setReadOnly(True)
                self.banner.setText(BINARY_BANNER)
                self.raw_box.setVisible(True)
            elif bc.is_cfg(f.rel) and (doc := bc.parse(self._text)).entries:
                self._doc = doc
                self._build_form(doc)
                self.form_scroll.setVisible(True)
                self._rebuild_jump()
                self._apply_search(scroll=False)
                if same and scroll_value:
                    bar = self.form_scroll.verticalScrollBar()
                    QTimer.singleShot(0, lambda: bar.setValue(scroll_value))
            else:
                self.raw_edit.setReadOnly(False)
                self.raw_edit.setPlainText(self._text.lstrip("﻿"))
                self.banner.setText(RAW_BANNER)
                self.raw_box.setVisible(True)
            kind = "form" if self._doc else "raw" if self._text is not None else "binary"
            log(f"edit config: showing {f.rel} ({kind}"
                f"{f', {len(self._doc.entries)} entries in {len(self._doc.sections)} sections' if self._doc else ''})")
        self.jump_bar.setVisible(self._doc is not None)
        if self._doc is None:
            self._rebuild_jump()
        self._mark_selected()
        self._refresh_actions()

    # ---- the parsed form ----
    def _build_form(self, doc: bc.ConfigDocument) -> None:
        self._form_gen += 1
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(0, 0, 4, 0)
        column.setSpacing(14)
        by_section: dict[str, list[bc.Entry]] = {}
        for entry in doc.entries:
            by_section.setdefault(entry.section, []).append(entry)
        for header in doc.sections:
            section = _Section(header)
            for entry in by_section[header]:
                row = self._build_row(entry)
                section.add_row(row)
                self._rows.append(row)
            column.addWidget(section)
            self._sections.append(section)
        self.no_match = _label("", "config-empty", wrap=True)  # Filter mode, no hits
        self.no_match.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_match.setContentsMargins(0, 24, 0, 24)
        self.no_match.setVisible(False)
        column.addWidget(self.no_match)
        column.addStretch(1)
        old = self.form_scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.form_scroll.setWidget(inner)
        _transparent(self.form_scroll)

    def _build_row(self, entry: bc.Entry) -> QWidget:
        # A widget of its own, not a bare nested QVBoxLayout. A nested box
        # layout reports its LAST child's maximum width as its own (Qt's
        # qMaxExpCalc), and QBoxLayout::setGeometry takes each child's
        # heightForWidth at a width bounded by that maximum - so a row ending
        # in a 260px drop-down / field had its height measured with the
        # description wrapped at 260px while being laid out at the pane's full
        # width. The scroll widget's own height came from the unclamped pass
        # (QScrollArea -> calcHfw), so the rows' summed over-estimates never
        # fit: Qt truncated the biggest sections and rows (cut-off fields, the
        # [Logging.Console] LogLevels check-box grid crushed into its own
        # rows) and left the small ones slack (the [Chainloader] gap, the
        # labels growing and centring their text). A QWidget's maximum width
        # is unbounded, so its rows are measured at the width they get.
        # (A QFrame since the search tints it as a card; the margins are the
        # card's border + padding, not layout slack.)
        box = _EntryRow(entry)
        row = QVBoxLayout(box)
        row.setContentsMargins(*ROW_MARGINS)
        row.setSpacing(3)
        box.key_label = _label(entry.key, "config-key")
        row.addWidget(box.key_label)
        if entry.description:
            box.desc_label = _label(entry.description, "config-desc", wrap=True)
            row.addWidget(box.desc_label)
        if entry.has_metadata:
            meta = f"Setting type: {entry.setting_type}"
            if entry.default is not None:
                meta += f" · Default value: {entry.default}"
            meta_line = _ElidedLabel("config-meta")  # a default can be a paragraph (AzuClock's Clock String)
            meta_line.set_text(meta)
            row.addWidget(meta_line)
        if entry.acceptable is not None:
            self._add_acceptable(row, entry)
        elif entry.value_range is not None:
            lo_, hi_ = entry.value_range
            row.addWidget(_label(f"Acceptable value range: From {lo_} to {hi_}", "config-meta"))
        control, getter = self._build_control(entry)
        row.addWidget(control)
        self._getters.append((entry, getter))
        box.finish()
        return box

    def _add_acceptable(self, row: QVBoxLayout, entry: bc.Entry) -> None:
        text = "Acceptable values: " + ", ".join(entry.acceptable)
        if entry.flags:
            text += "  (several can be set, separated by commas)"
        one_line = _ElidedLabel("config-meta")
        one_line.set_text(text)
        row.addWidget(one_line)
        if len(entry.acceptable) <= bc.MANY_VALUES:
            return
        full = _label(text, "config-meta", wrap=True)
        full.setVisible(False)
        row.addWidget(full)
        more = _link(f"Show more ({len(entry.acceptable)} values)")

        def toggle() -> None:
            expanded = not full.isVisible()
            full.setVisible(expanded)
            one_line.setVisible(not expanded)
            more.setText("Show less" if expanded else f"Show more ({len(entry.acceptable)} values)")

        more.clicked.connect(lambda: toggle())
        row.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)

    def _build_control(self, entry: bc.Entry):
        """The control for one entry and a getter returning its current
        serialized value."""
        kind = bc.control_kind(entry)
        changed = self._refresh_actions
        if kind in ("enum", "bool", "shortcut"):
            combo = QComboBox()
            combo.setFixedWidth(FIELD_WIDTH)
            options = ["true", "false"] if kind == "bool" else list(entry.acceptable or [])
            current = entry.value
            if kind == "shortcut":  # "Z + LeftAlt": typed, or one key picked from the KeyCode list
                options = options or list(bc.UNITY_KEYCODES)
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.addItems(options)
                combo.setCurrentText(current)
                combo.currentTextChanged.connect(lambda _t: changed())
                return combo, lambda: combo.currentText().strip()
            if current not in options:  # a hand-edited / unknown value: keep it selectable
                options.insert(0, current)
            combo.addItems(options)
            combo.setCurrentIndex(options.index(current))
            combo.currentIndexChanged.connect(lambda _i: changed())
            return combo, lambda: combo.currentText()
        if kind == "flags":
            box = QWidget()
            grid = QGridLayout(box)
            grid.setContentsMargins(0, 2, 0, 0)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(4)
            chosen = set(bc.split_flags(entry.value))
            checks: list[tuple[str, QCheckBox]] = []
            for i, name in enumerate(entry.acceptable):
                check = QCheckBox(name)
                check.setChecked(name in chosen)
                check.toggled.connect(lambda _on: changed())
                grid.addWidget(check, i // FLAG_COLUMNS, i % FLAG_COLUMNS)
                checks.append((name, check))
            return box, lambda: bc.join_flags([n for n, c in checks if c.isChecked()], entry.acceptable)
        if kind in ("int", "float"):
            field = QLineEdit(entry.value)
            field.setFixedWidth(NUMBER_WIDTH)
            field.setValidator(QRegularExpressionValidator(_INT_RE if kind == "int" else _FLOAT_RE, field))
            if entry.value_range is not None:
                field.setToolTip(f"From {entry.value_range[0]} to {entry.value_range[1]}")
            field.textChanged.connect(lambda _t: changed())
            return field, lambda: field.text().strip()
        if kind == "color":
            return self._build_color(entry)
        if kind == "long-text":
            box = QWidget()
            column = QVBoxLayout(box)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(3)
            edit = QPlainTextEdit()
            edit.setPlainText(entry.value)
            edit.setFixedHeight(LONG_TEXT_HEIGHT[0])
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            edit.textChanged.connect(lambda: changed())
            column.addWidget(edit)
            more = _link("Show more")
            expanded = [False]

            def toggle() -> None:
                expanded[0] = not expanded[0]
                edit.setFixedHeight(LONG_TEXT_HEIGHT[expanded[0]])
                more.setText("Show less" if expanded[0] else "Show more")

            more.clicked.connect(lambda: toggle())
            column.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
            box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return box, lambda: edit.toPlainText()
        field = QLineEdit(entry.value)
        field.setFixedWidth(FIELD_WIDTH)
        field.textChanged.connect(lambda _t: changed())
        return field, lambda: field.text()

    def _build_color(self, entry: bc.Entry):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 2, 0, 0)
        row.setSpacing(8)
        swatch = QPushButton()
        swatch.setProperty("variant", "config-swatch")
        swatch.setFixedSize(22, 22)
        swatch.setAutoDefault(False)
        swatch.setToolTip("Pick a color")
        swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        field = QLineEdit(entry.value)
        field.setProperty("mono", True)
        field.setFixedWidth(COLOR_WIDTH)
        field.setValidator(QRegularExpressionValidator(_HEX_RE, field))

        def paint() -> None:
            rgba = bc.color_to_rgb(field.text())
            css = f"#{field.text()[:6]}" if rgba else "transparent"
            swatch.setStyleSheet(f"QPushButton {{ background: {css}; }}")
            self._refresh_actions()

        def pick() -> None:
            rgba = bc.color_to_rgb(field.text()) or (255, 255, 255, 255)
            color = QColorDialog.getColor(QColor(*rgba), self, "Pick a color",
                                          QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if color.isValid():
                field.setText(bc.rgb_to_color(color.red(), color.green(), color.blue(), color.alpha()))

        field.textChanged.connect(lambda _t: paint())
        swatch.clicked.connect(lambda: pick())
        paint()
        row.addWidget(swatch)
        row.addWidget(field)

        def value() -> str:
            v = field.text().strip()
            return v.upper() if bc.color_to_rgb(v) else v

        return box, value

    # ---- dirty / actions ----
    def _form_changes(self) -> list[tuple[bc.Entry, str]]:
        return [(entry, v) for entry, get in self._getters if (v := get().strip()) != entry.value]

    def _dirty(self) -> bool:
        if self._current is None or self._text is None:
            return False
        if self._doc is not None:
            return bool(self._form_changes())
        return self.raw_edit.toPlainText() != self._text.lstrip("﻿")

    def _refresh_actions(self) -> None:
        has = self._current is not None
        dirty = self._dirty()
        self.save_button.setEnabled(dirty)
        self.revert_button.setEnabled(dirty)
        self.delete_button.setEnabled(has)
        self.open_button.setEnabled(has)

    def _confirm_discard(self) -> bool:
        if not self._dirty():
            return True
        box = QMessageBox(QMessageBox.Icon.Question, "Unsaved changes",
                          f"Discard unsaved changes to {self._current.rel}?", QMessageBox.StandardButton.Cancel, self)
        discard = box.addButton("Discard changes", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(discard)  # Enter confirms (user decision 2026-09-29)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)  # Esc still cancels
        box.exec()
        confirmed = box.clickedButton() is discard
        log(f"edit config: discard prompt for {self._current.rel} -> {'discard' if confirmed else 'cancel'}")
        return confirmed

    def _warn(self, title: str, message: str) -> None:
        log(f"edit config: warning shown: {title}: {message}")
        QMessageBox.warning(self, title, message)

    def reject(self) -> None:  # Close, Esc and the title-bar X all land here
        if self._confirm_discard():
            super().reject()

    # ---- Save / Revert / Delete / Open ----
    def _save(self) -> None:
        f = self._current
        if f is None or self._text is None or not self._dirty():
            return
        if self._doc is not None:
            changes = self._form_changes()
            for entry, value in changes:
                self._doc.set_value(entry, value)
            text = self._doc.render()
            what = ", ".join(f"[{e.section}] {e.key} = {v}" for e, v in changes)
        else:
            body = self.raw_edit.toPlainText()
            if "\r\n" in self._text:
                body = body.replace("\n", "\r\n")
            text = ("﻿" if self._text.startswith("﻿") else "") + body
            what = f"raw text, {len(body)} chars"
        try:
            bc.write_text(f.path, text)
        except OSError as err:
            log(f"edit config: save {f.path} failed: {err}")
            self._warn("Couldn't save", f"{f.rel}\n\n{err}")
            return
        log(f"edit config: saved {f.rel}: {what}")
        self._show_file(f)  # re-read from disk: what the form shows is what was written
        self._refresh_file_stats()

    def _revert(self) -> None:
        if self._current is not None and self._dirty():
            log(f"edit config: reverted edits to {self._current.rel}")
            self._show_file(self._current)

    def _delete(self) -> None:
        f = self._current
        if f is None:
            return
        box = QMessageBox(QMessageBox.Icon.Question, "Delete config file",
                          f"Delete {f.rel}?\n\nThe file is removed from disk; this can't be undone. A mod that "
                          "needs it writes a fresh default one the next time the load order runs.",
                          QMessageBox.StandardButton.Cancel, self)
        delete = box.addButton("Delete", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(delete)  # Enter confirms (user decision 2026-09-29)
        box.setEscapeButton(QMessageBox.StandardButton.Cancel)  # Esc still cancels
        box.exec()
        if box.clickedButton() is not delete:
            log(f"edit config: delete {f.rel}: cancelled")
            return
        try:
            f.path.unlink()
        except OSError as err:
            log(f"edit config: delete {f.path} failed: {err}")
            self._warn("Couldn't delete", f"{f.rel}\n\n{err}")
            return
        log(f"edit config: deleted {f.rel}")
        self._current = None
        self.reload_files()
        self._show_file(None)

    def _open_externally(self) -> None:
        f = self._current
        if f is None:
            return
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(f.path)))
        log(f"edit config: open externally {f.path}: {'opened' if opened else 'FAILED (openUrl returned false)'}")

    def _refresh_file_stats(self) -> None:
        """After a save: the list's size / modified data without losing the
        selection (a Modified sort reorders)."""
        current = self._current
        self._files_all = bc.list_config_files(self._bepinex_dir, all_files=True)
        if current is not None:
            self._current = next((f for f in self._files_all if f.path == current.path), None)
        self._rebuild_list()
