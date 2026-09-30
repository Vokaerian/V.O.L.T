"""The details panel (port of DetailsPanel.jsx): the selected mod's preview
image (About/Preview.png, when present), name, authors, source (where it
comes from: mods.origin, 0.6.8), path, package ID and description - or, for a selected "not found" row (an id with no scanned mod,
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

0.6.8 follow-up (DESIGN.md, the RimWorld details readout): the same Circuit
readout as the Valheim pane - readout() / details_well() below, shared with
bepinex_main_screen.ThunderstoreDetailsPanel - with the preview on
painters.ThumbFrame. PATH shows only its meaningful tail (display_path) and
PATH / PACKAGE ID carry zero-width soft breaks so a long value wraps
instead of clipping; ValueLabel keeps the full value for its tooltip and
copies it clean (no break characters) from its right-click menu and Ctrl+C.
"""

import re
from pathlib import Path, PurePath

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QMenu, QScrollArea, QVBoxLayout, QWidget

from volt_py import mods, painters, theme
from volt_py.fsutil import find_child_ci
from volt_py.mod_list_io import not_found_workshop_id

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


# ---- PATH / PACKAGE ID display (Qt-free; tools/checks/volt_py_design_phase2.py) ----

ZWSP = "\u200b"  # a zero-width space: an invisible line-break opportunity QLabel's word wrap honours
PATH_BREAKS = "\\/"  # soft break after each path separator
PACKAGE_BREAKS = "."  # ... and after each dot of a package id
ELLIPSIS = "\u2026"


def soft_breaks(text: str, chars: str) -> str:
    """`text` with a ZWSP after every character in `chars`, so a long value
    with no spaces (a path, a package id) wraps there instead of clipping."""
    return "".join(c + ZWSP if c in chars else c for c in text)


def clean_breaks(text: str) -> str:
    """The inverse: `text` without the soft breaks (what gets copied)."""
    return text.replace(ZWSP, "")


def display_path(path, source: str | None) -> str:
    """The part of a mod's folder that tells mods apart, behind a leading
    ellipsis: a Steam Workshop item's last 5 parts
    (steamapps\\workshop\\content\\294100\\<id>), anything in the game folder
    its last 3 (<game folder>\\Mods\\<folder>, <game folder>\\Data\\Core) - the
    real folder names, whatever they are. A path that short already is shown
    whole. A str is read as a Path (the platform's separators)."""
    p = path if isinstance(path, PurePath) else Path(path)
    keep = 5 if source == "workshop" else 3
    if len(p.parts) <= keep + 1:  # nothing (or only the drive) would be dropped
        return str(p)
    sep = "\\" if "\\" in str(p) else "/"
    return ELLIPSIS + sep + sep.join(p.parts[-keep:])


def value_view(full: str, shown: str | None = None, breaks: str = "", tip: bool = False) -> tuple[str, str]:
    """(label text, tooltip) for a details value: `shown` (default: `full`)
    with soft breaks after `breaks`, and the full value as the tooltip when
    `tip`."""
    text = full if shown is None else shown
    return (soft_breaks(text, breaks) if breaks else text), (full if tip else "")


def copy_value(full: str, label_text: str, selected: str) -> str:
    """What Ctrl+C copies: the selection without its soft breaks - or the
    full value when nothing, or the whole shown text, is selected (so a
    selected PATH tail copies the whole path)."""
    sel = clean_breaks(selected)
    return full if not sel or sel == clean_breaks(label_text) else sel


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


class ValueLabel(QLabel):
    """A RimWorld details value (0.6.8 follow-up): plain wrapped selectable
    text set by set_value, which keeps the full value. Right-click offers
    "Copy <row>" (the full value) and, with part of it selected, "Copy
    selection"; Ctrl+C copies per copy_value. Both leave the soft breaks
    out - QLabel's own menu / copy would keep them (a path pasted into
    Explorer would fail). Click focus, so Ctrl+C reaches it after a click."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # A word-wrapped QLabel's minimum width is its longest unbreakable
        # word. That once lifted the rows' minimum width past the pane's, and
        # QBoxLayout asks a height-for-width item for its height at
        # max(minimum width, actual width): the rows were sized for a wider
        # pane than they got and a row that wraps only at the real width came
        # up a line short (0.6.8). A 1px floor keeps the minimum out of it;
        # the soft breaks now let a long path / package id wrap too.
        self.setMinimumWidth(1)
        self._copy_label = f"Copy {title[0].lower()}{title[1:]}"
        self._full = ""

    def heightForWidth(self, width: int) -> int:
        # QLabel measures wrapped text in whole logical px (QFontMetrics) but
        # paints it at the screen's fractional scale: at 125% a value wrapped
        # to 2 lines came up a few px short and its last line lost its
        # descenders to the rule below (hardware, 0.6.8 follow-up). A single-
        # line row never showed it - the key cell, with its baseline nudge, is
        # the taller one there - so this descent of slack only grows a row
        # whose value is its tallest cell, i.e. a wrapped one.
        height = super().heightForWidth(width)
        return height + self.fontMetrics().descent() if height > 0 else height

    def set_value(self, full: str, shown: str | None = None, *, breaks: str = "", tip: bool = False) -> None:
        self._full = full
        text, tooltip = value_view(full, shown, breaks, tip)
        self.setText(text)
        self.setToolTip(tooltip)

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction(self._copy_label).triggered.connect(lambda: self._copy(self._full))
        selected = clean_breaks(self.selectedText())
        if selected and selected != clean_breaks(self.text()):
            menu.addAction("Copy selection").triggered.connect(lambda: self._copy(selected))
        menu.exec(event.globalPos())

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy(copy_value(self._full, self.text(), self.selectedText()))
            event.accept()
            return
        super().keyPressEvent(event)


# The readout (step 3.1, DESIGN.md §15; RimWorld too since the 0.6.8
# follow-up): the mockup's key column, 2px row padding + a 106px .dkey, so
# the values line up at 108px whatever the widest key measures.
READOUT_KEY_WIDTH = 108
# The ascent difference alone left the keys 6 device px (~5 px) above their
# values' baseline at 125% on hardware (0.5.9): the selectable value labels
# lay their text out lower than a plain label does. Measured correction;
# re-check on a second DPR (step 3.1 amendment).
_KEY_BASELINE_NUDGE = 5


def readout(rows: list[tuple[str, QLabel]]) -> QGridLayout:
    """The details pane as a readout: `rows` of (key title, value label),
    copper terminal keys with a 1px rule between the rows - a grid with no
    spacing, so key and value cells share each row's height and the rule
    (theme.py's readout / details-value / first rules) runs unbroken."""
    form = QGridLayout()
    form.setHorizontalSpacing(0)
    form.setVerticalSpacing(0)
    form.setColumnStretch(1, 1)
    form.setColumnMinimumWidth(0, READOUT_KEY_WIDTH)
    keys: list[QLabel] = []
    for row, (title, value) in enumerate(rows):
        label = details_key(title)
        label.setProperty("readout", True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        value.setProperty("role", "details-value")
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        for cell in (label, value):
            cell.setProperty("first", row == 0)
        form.addWidget(label, row, 0)
        form.addWidget(value, row, 1)
        keys.append(label)
    # Baseline-align each key with its value's first line: the mono key
    # has a smaller ascent than the 13px value (the rules stay aligned -
    # this only pads the key's text down inside its cell).
    first_value = rows[0][1]
    first_value.ensurePolished()
    for label in keys:
        label.ensurePolished()
        drop = first_value.fontMetrics().ascent() - label.fontMetrics().ascent()
        label.setContentsMargins(0, max(0, drop) + _KEY_BASELINE_NUDGE, 0, 0)
    return form


def details_well(text: QLabel) -> QFrame:
    """The description's recessed well (theme.py QFrame#detailsWell): `text`
    in a scroll area inside the 1px border, the 7px top shade strip over it.
    The caller adds it with stretch 1 (it takes the pane's leftover height)."""
    text.setObjectName("detailsWellText")
    text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    well = QFrame()
    well.setObjectName("detailsWell")
    well_layout = QGridLayout(well)
    well_layout.setContentsMargins(1, 1, 1, 1)
    well_layout.setSpacing(0)
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(text)
    # Let the well show through (setWidget turns autofill on).
    scroll.viewport().setAutoFillBackground(False)
    text.setAutoFillBackground(False)
    well_layout.addWidget(scroll, 0, 0)
    shade = QWidget()
    shade.setObjectName("detailsWellShade")
    shade.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    shade.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    shade.setFixedHeight(7)
    well_layout.addWidget(shade, 0, 0, Qt.AlignmentFlag.AlignTop)
    return well


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
        self.details_preview = painters.ThumbFrame()  # Preview.png on its framed mat (0.6.8 follow-up)
        self.details_preview.setVisible(False)
        body_layout.addWidget(self.details_preview, 0, Qt.AlignmentFlag.AlignHCenter)

        self.details_fields: dict[str, ValueLabel] = {}
        rows = []
        for key, title in (
            ("name", "Name"),
            ("authors", "Authors"),
            ("source", "Source"),  # mods.origin, the same text as the mod menu's header (0.6.8)
            ("path", "Path"),
            ("package_id", "Package ID"),
        ):
            rows.append((title, ValueLabel(title)))
            self.details_fields[key] = rows[-1][1]
        body_layout.addLayout(readout(rows))

        # .details-description: in the recessed well, fills the rest, scrolls on overflow.
        self.details_description = _details_text()
        body_layout.addWidget(details_well(self.details_description), 1)
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
            f["name"].set_value(title or missing_id)
            f["authors"].set_value("-")
            f["source"].set_value(mods.origin(None, bool(not_found_workshop_id(missing_id, {})))[1])
            f["path"].set_value(NOT_FOUND_PATH)
            f["package_id"].set_value(missing_id, breaks=PACKAGE_BREAKS, tip=True)
            self.details_description.setText(NOT_FOUND_NOTE)
            self._preview_source = None
            self._update_preview_pixmap()
            return
        f["name"].set_value(mod["name"])
        f["authors"].set_value(", ".join(mod["authors"]) or "-")
        f["source"].set_value(mods.origin(mod)[1])
        f["path"].set_value(str(mod["path"]), display_path(mod["path"], mod["source"]), breaks=PATH_BREAKS, tip=True)
        f["package_id"].set_value(mod["package_id"] or "(none)", breaks=PACKAGE_BREAKS, tip=bool(mod["package_id"]))
        self.details_description.setText(clean_description(mod["description"]) or "No description.")

        about = find_child_ci(mod["path"], "About")
        preview = about and find_child_ci(about, "Preview.png")
        self._preview_source = QPixmap(str(preview)) if preview else None
        self._update_preview_pixmap()

    def _update_preview_pixmap(self) -> None:
        pixmap = self._preview_source
        # .details-preview: at most the pane's width and 35% of its height,
        # the frame's mat / margins included (as the Valheim icon), aspect kept.
        chrome_w, chrome_h = painters.thumb_chrome()
        box_w, box_h = self.width() - 20 - chrome_w, int(self.height() * 0.35) - chrome_h
        if pixmap is None or pixmap.isNull() or box_w <= 0 or box_h <= 0:
            self.details_preview.setVisible(False)
            return
        # Always scale from the unscaled original (repeated resizes don't
        # compound blur), smoothly: ThumbFrame only draws what it's given, and
        # a 1920px preview drawn straight into ~250px would alias.
        if pixmap.width() > box_w or pixmap.height() > box_h:
            pixmap = pixmap.scaled(
                QSize(box_w, box_h), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        self.details_preview.set_image(pixmap, box_w, box_h)
        self.details_preview.setVisible(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_preview_pixmap()
