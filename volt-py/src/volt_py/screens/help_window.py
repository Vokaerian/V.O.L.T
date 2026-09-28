"""Help window: a read-only reference of what each control does. A modal
dialog shaped like the Scan issues window (screens/scan_issues_window.py):
header with the title and Close, then a rail of entry names (alphabetical)
beside a detail pane for the selected entry (name, one-line summary, longer
explanation).

Game-agnostic on purpose (cross-game shell element, PLAN.md §7): the window
only knows the entry shape, never a game. Each game supplies its own list of
{"name": str, "short": str, "long": str} dicts (RimWorld's:
screens/rimworld_help_entries.py) and opens it with
`HelpWindow(entries, parent=self).exec()`.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

# Same box as the Scan issues / Warnings and errors windows: 900 x 600, at
# most the parent window minus 32px.
WINDOW_SIZE = (900, 600)
RAIL_WIDTH = 240


def sorted_entries(entries: list[dict]) -> list[dict]:
    """Alphabetical by name, case-insensitive."""
    return sorted(entries, key=lambda entry: entry["name"].casefold())


def _repolish(widget: QWidget) -> None:
    # A property selector isn't re-evaluated on its own after the first polish.
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _text(role: str) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setProperty("role", role)
    return label


def _transparent(scroll: QScrollArea) -> None:
    # Let the scroll area's own QSS background show through (setWidget turns autofill on).
    scroll.viewport().setAutoFillBackground(False)
    scroll.widget().setAutoFillBackground(False)


class HelpWindow(QDialog):
    def __init__(self, entries: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self._long = _text("help-long")
        for label in (self._heading, self._short, self._long):
            detail.addWidget(label)
        detail.addStretch(1)
        scroll.setWidget(inner)
        _transparent(scroll)
        return scroll

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
