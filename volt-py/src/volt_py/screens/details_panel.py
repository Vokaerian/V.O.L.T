"""The details panel (port of DetailsPanel.jsx): the selected mod's preview
image (About/Preview.png, when present), name, authors, path, package ID and
description - or, for a selected "not found" row (an id with no scanned mod,
e.g. a pending Workshop id), DetailsPanel.jsx's not-found view: its name
(the Workshop title when known, else the id), no authors, a "not found"
path, the id as package ID and the not-found note.

One widget class, used by the RimWorld main screen (its left column) and by
the Validation window (screens/validation_window.py, top right) - the
Electron app shares its DetailsPanel component the same way. Moved here
unchanged from rimworld_main_screen.py (_build_details_panel / _show_details
/ _update_preview_pixmap / _clean_description) when the Validation window
needed a second one; the only difference is that the panel rescales its
preview from its own resizeEvent instead of the main screen's.
"""

import re

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from volt_py import painters, theme
from volt_py.fsutil import find_child_ci

# DetailsPanel.jsx: a not-found row's path and description, verbatim.
NOT_FOUND_PATH = "Not found in any scanned folder"
NOT_FOUND_NOTE = (
    "This mod is in the load order but wasn't found in the game's Data or Mods folder (or, for Steam, the "
    "Workshop folder) - it may be uninstalled or unsubscribed. It is kept in the list and written as-is on Save "
    "and Push."
)

# lists.js cleanDescription: strips RimWorld's Unity rich-text tags.
_UNITY_TAGS = re.compile(r"</?(?:color|b|i|size|material|quad)(?:=[^>]*)?>", re.IGNORECASE)


def clean_description(text: str | None) -> str:
    return _UNITY_TAGS.sub("", text or "").replace("\r\n", "\n")


def _label(text: str, *, muted: bool = False) -> QLabel:
    label = QLabel(text)
    if muted:
        label.setProperty("muted", True)
    return label


def details_key(text: str) -> QLabel:
    """A details-pane key as a Circuit terminal label (step 3.1, both games):
    copper mono spaced caps (theme.py's QLabel[role="details-key"]; the caps
    and spacing are on its font - QSS has neither). No colon: the copper
    column is the separator."""
    label = QLabel(text)
    label.setProperty("role", "details-key")
    label.setFont(painters.terminal_font(painters.TERMINAL_KEY_PX, painters.TERMINAL_KEY_SPACING))
    return label


def _details_text() -> QLabel:
    # Plain text: mod metadata can contain '<' (Unity tags, generics).
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class DetailsPanel(QFrame):
    """aside.details: "Select a mod to see its details." until show_mod gets
    a mod, then its preview / fields / description."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("panel", True)
        self._preview_source: QPixmap | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        empty = self.details_empty = _label("Select a mod to see its details.", muted=True)
        empty.setWordWrap(True)
        # It's a <p> in the Electron app: default 1em (13px) top margin,
        # top-left aligned inside the panel.
        empty.setContentsMargins(0, theme.FONT_SIZE_PX, 0, 0)
        empty.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addWidget(empty, 1)

        body = self.details_body = QWidget()
        body.setVisible(False)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        self.details_preview = QLabel()  # .details-preview
        self.details_preview.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        body_layout.addWidget(self.details_preview)

        form = QFormLayout()  # .details-grid
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        self.details_fields: dict[str, QLabel] = {}
        for key, title in (
            ("name", "Name"),
            ("authors", "Authors"),
            ("path", "Path"),
            ("package_id", "Package ID"),
        ):
            value = self.details_fields[key] = _details_text()
            form.addRow(details_key(title), value)
        body_layout.addLayout(form)

        # .details-description: fills the rest, scrolls on overflow.
        self.details_description = _details_text()
        self.details_description.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.details_description)
        # Let the panel background show through (setWidget turns autofill on).
        scroll.viewport().setAutoFillBackground(False)
        self.details_description.setAutoFillBackground(False)
        body_layout.addWidget(scroll, 1)
        layout.addWidget(body, 1)

    def show_mod(self, mod: dict | None, missing_id: str | None = None, title: str | None = None) -> None:
        """Shows `mod` (a scanned mod). With no mod, `missing_id` is a
        selected row whose id didn't scan (DetailsPanel.jsx's `id` without a
        `mod`): the not-found view, named `title` (its pendingTitle: a
        not-found Workshop id's title, when known) else the id, with no
        preview. Neither: the empty message."""
        shown = mod is not None or bool(missing_id)
        self.details_empty.setVisible(not shown)
        self.details_body.setVisible(shown)
        if not shown:
            return
        f = self.details_fields
        if mod is None:
            f["name"].setText(title or missing_id)
            f["authors"].setText("-")
            f["path"].setText(NOT_FOUND_PATH)
            f["package_id"].setText(missing_id)
            self.details_description.setText(NOT_FOUND_NOTE)
            self._preview_source = None
            self._update_preview_pixmap()
            return
        f["name"].setText(mod["name"])
        f["authors"].setText(", ".join(mod["authors"]) or "-")
        f["path"].setText(str(mod["path"]))
        f["package_id"].setText(mod["package_id"] or "(none)")
        self.details_description.setText(clean_description(mod["description"]) or "No description.")

        about = find_child_ci(mod["path"], "About")
        preview = about and find_child_ci(about, "Preview.png")
        self._preview_source = QPixmap(str(preview)) if preview else None
        self._update_preview_pixmap()

    def _update_preview_pixmap(self) -> None:
        # Always scale from the unscaled original, so repeated resizes don't compound blur.
        pixmap = self._preview_source
        if pixmap is None or pixmap.isNull():
            self.details_preview.setPixmap(QPixmap())
            self.details_preview.setVisible(False)
            return
        # .details-preview: max-width 100%, max-height 35%, aspect kept.
        box = QSize(self.width() - 20, int(self.height() * 0.35))
        if pixmap.width() > box.width() or pixmap.height() > box.height():
            pixmap = pixmap.scaled(
                box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        self.details_preview.setPixmap(pixmap)
        self.details_preview.setVisible(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview_pixmap()
