"""The Thunderstore/BepInEx manager's mod-list rows (THUNDERSTORE.md §3; the
signed-off Valheim main-screen mockup's .vh-row / .vh-toggle /
.vh-update-btn, https://claude.ai/artifact/KeNe4nnwPVmCgfxrpbXBCZ).
Game-agnostic: Valheim's screen uses it today, the next BepInEx game
(Lethal Company, R.E.P.O.) reuses it as-is.

Built on screens/mod_list.py's ModListView / ModRowDelegate - the model,
search (query + eye), click-to-deselect, double-click moves and the
drag-reorder preview/animation are all inherited unchanged. What differs:

  - Rows are CARD_HEIGHT (54px) tall, two lines: the mod's display name on
    line 1 (13px, --text), a drawn warning icon in --warn after it when an update is
    available and a drawn x in --danger when a dependency is missing (its
    tooltip names it); before the name, Thunderstore Mod Manager's status
    pills - mod_list.py's .row-badge box (paint_row_badge): "Disabled" in
    --warn on an Active row whose toggle is off (the name then --muted and
    struck through), "Deprecated" in --danger on a package Thunderstore
    marks deprecated (RowInfo.disabled / .deprecated; Disabled first when
    both); "v<version> · <last updated>" on line 2 (12px,
    --muted; --warn reading "update available" when there is one). The
    base paint still draws the card (theme.py's ::item rules: background,
    hover, selected, radius, margins) - initStyleOption blanks the item
    text, and _paint_card paints the two lines and the controls itself,
    under the same clip / opacity as the card (search dim, drag fade).
  - The pinned framework row (RowInfo.pinned): a 3px --accent bar down the
    card's left edge (the mockup's inset box-shadow; paint_match_bar draws
    exactly that) and a muted 11px "Pinned" tag where the toggle would sit;
    never draggable (a press on it never becomes a drag), never a drop
    target (a drag can't land above it), no toggle.
  - Per-mod controls, painted (not widgets) and hit-tested exactly like
    mod_list.py's issue icons / Subscribe button (control_at -> the press is
    taken whole, fires on a release over the same control of the same mod,
    hand cursor, own tooltip, a hover look): the on/off toggle pill
    (TOGGLE, 34x18, right end of the card; RowInfo.toggle None = none, as
    on Inactive rows and the framework row) and the yellow up-arrow update
    button (UPDATE, 24x24, ACTIONS_GAP left of the toggle - or of the
    Pinned tag / the right edge) - painted only while RowInfo.update says
    an update is available (hidden, not disabled, otherwise). Both are
    disabled (half opacity, no hover look, no click) while the screen's
    controls_enabled() says it's busy; an update in flight (RowInfo.busy)
    disables just that row's button.

  - The mod's icon (0.6.26, PLAN.md §11 (b); DESIGN.md §37): a ROW_ICON_PX
    square tile at the card's left (ROW_PAD in, vertically centered) - the
    package's icon, pre-rounded by the screen (RowInfo.icon), or a plain
    --well tile while there is none (not loaded yet, no icon.png). The two
    text lines (and the status pills) start ROW_ICON_PX + ROW_PAD further
    right than before; nothing else moved, and the icon is never a control.
  - "Files missing" (0.6.27, PLAN.md §11 (f); DESIGN.md §38): a third status
    pill in --warn, after Disabled / Deprecated, on a mod some of whose
    files are gone from the profile folder (RowInfo.files_missing; the row's
    tooltip says what and how to fix it). The same pill family and box as
    the other two; on any other row nothing changes.

The screen supplies everything per row through `row_info` (mod id ->
RowInfo) at paint / hit-test time - nothing is stored here, as with
mod_list.py's `decor` callable - and takes the clicks through `on_update`
(mod id) and `on_toggle` (mod id, new state).
"""

import time
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from volt_py import icons, painters, theme
from volt_py.applog import log
from volt_py.screens.mod_list import (
    DIMMED_ROW_OPACITY,
    DISABLED_BUTTON_OPACITY,
    BADGE_HEIGHT,
    DRAGGED_ROW_OPACITY,
    MARK_DIM,
    MARK_MATCH,
    ModListView,
    ModRowDelegate,
    badge_font,
    badge_width,
    paint_match_bar,
    paint_row_badge,
)

# The mockup's .vh-row and children (px).
CARD_HEIGHT = 54  # .vh-row height
ROW_PAD = 10  # .vh-row padding: 0 10px, and its gap between the text block and the actions
LINE_GAP = 2  # .vh-row-text gap
META_FONT_PX = 12  # .vh-row-meta font-size
NAME_GAP = 6  # .vh-row-name gap: name | warn icon | x icon
ACTIONS_GAP = 8  # .vh-row-actions gap: update button | toggle
TOGGLE_W, TOGGLE_H = 34, 18  # .vh-toggle
KNOB = 14  # .vh-toggle-knob; 1px inside the 1px border: 2px from the pill's edge
UPDATE_SIZE = 24  # .vh-update-btn
TAG_FONT_PX = 11  # .tag font-size ("Pinned")
# The icon tile (0.6.26): the Browse Mods card's icon size and corner (bepinex_browse_window
# ICON_PX / ICON_RADIUS), without its mat - 7px above and below it in the 54px card.
ROW_ICON_PX = 40
ROW_ICON_RADIUS = 3

UPDATE = "update"
TOGGLE = "toggle"
PINNED = "pinned"  # the Pinned tag's slot: laid out with the controls, never clickable
# The name's marks: drawn icons (icons.py; were the ⚠ / ✕ glyphs - Windows drew
# the ⚠ as a color emoji), MARK_PX square, cached per color and scale.
WARN_MARK = "warn"
ERROR_MARK = "x"
MARK_PX = 14
UPDATE_GLYPH = "↑"
PINNED_TEXT = "Pinned"
DISABLED_TEXT = "Disabled"  # the status pills before the name (RowInfo.disabled / .deprecated)
DEPRECATED_TEXT = "Deprecated"
FILES_MISSING_TEXT = "Files missing"
# The toggle slide (phase 4 M4, memory/DESIGN.md §27-29): a single clicked
# toggle's knob slides over theme.MOTION_FAST, css_ease; frames every
# TOGGLE_FRAME_MS, repainting only the sliding toggles.
TOGGLE_FRAME_MS = 16
_EASE = painters.css_ease()  # one curve, valueForProgress per frame


class RowInfo(NamedTuple):
    """One row, as the screen describes it (row_info(mod id))."""

    name: str  # line 1
    meta: str  # line 2 ("v2.30.2 · Updated 12d ago", "v2.30.2 · update available", ...)
    meta_warn: bool = False  # line 2 in --warn (an update is available)
    pinned: bool = False  # the framework row: accent bar, Pinned tag, no toggle, not draggable
    toggle: bool | None = None  # the toggle's state; None = no toggle on this row
    update: bool = False  # paint the update button (an update is available)
    warn: bool = False  # a warning icon after the name
    error: str | None = None  # an x icon after the name, with this tooltip (a missing dependency)
    busy: bool = False  # this mod's update is in flight: its button disabled
    update_tip: str = ""  # the update button's tooltip ("Update Jotunn to 2.31.0")
    disabled: bool = False  # "Disabled" pill + muted struck-through name (an Active row toggled off)
    deprecated: bool = False  # "Deprecated" pill (Thunderstore marks the package deprecated)
    icon: object = None  # QPixmap, ROW_ICON_PX square, pre-rounded (rounded_pixmap); None = the placeholder tile
    files_missing: bool = False  # "Files missing" pill (some of the mod's files are gone from the profile folder)


def card_rect(rect, viewport, view) -> QRect:
    """The row card inside item rect `rect`: clipped to the viewport's right
    edge (a list-mode row rect is as wide as the widest row), then inset by
    `view`'s ::item margins (theme.row_margins: the rail's gutter on the
    left), as ModListView._card_rect."""
    left, top, right, bottom = theme.row_margins(view)
    r = QRect(rect)
    r.setRight(min(r.right(), viewport.right()))
    return r.adjusted(left, top, -right, -bottom)


def meta_font(widget: QWidget) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(META_FONT_PX)
    return font


def tag_font(widget: QWidget) -> QFont:
    font = QFont(widget.font())
    font.setPixelSize(TAG_FONT_PX)
    return font


def bold_font(font: QFont) -> QFont:
    out = QFont(font)
    out.setBold(True)
    return out


def tag_width(widget: QWidget) -> int:
    return QFontMetrics(tag_font(widget)).horizontalAdvance(PINNED_TEXT)


def layout_row(info: RowInfo, rect, viewport, widget: QWidget) -> dict[str, QRect]:
    """Where the row's right-end pieces go, on a row painted at item rect
    `rect` (viewport px): TOGGLE (or, on the pinned row, the PINNED tag) at
    the card's right edge less ROW_PAD, vertically centered, then UPDATE
    ACTIONS_GAP left of it (or at the right edge itself when the row has
    neither). Only the pieces the row has."""
    card = card_rect(rect, viewport, widget)
    right = card.right() - ROW_PAD
    cy = card.top() + card.height() // 2
    out: dict[str, QRect] = {}
    if info.toggle is not None:
        r = QRect(right - TOGGLE_W + 1, cy - TOGGLE_H // 2, TOGGLE_W, TOGGLE_H)
        out[TOGGLE] = r
        right = r.left() - 1 - ACTIONS_GAP
    elif info.pinned:
        w = tag_width(widget)
        h = QFontMetrics(tag_font(widget)).height()
        r = QRect(right - w + 1, cy - h // 2, w, h)
        out[PINNED] = r
        right = r.left() - 1 - ACTIONS_GAP
    if info.update:
        out[UPDATE] = QRect(right - UPDATE_SIZE + 1, cy - UPDATE_SIZE // 2, UPDATE_SIZE, UPDATE_SIZE)
    return out


def icon_rect(card: QRect) -> QRect:
    """The icon tile's rect inside card rect `card`: ROW_PAD in from the
    left, vertically centered."""
    return QRect(card.left() + ROW_PAD, card.top() + (card.height() - ROW_ICON_PX) // 2, ROW_ICON_PX, ROW_ICON_PX)


def paint_row_icon(painter: QPainter, rect: QRect, icon, dpr: float) -> None:
    """The icon (a pixmap at the screen's DPR) or the --well placeholder
    tile, its corner snapped to a device pixel (crisp at 125%). The caller
    saves/restores."""
    x, y = round(rect.left() * dpr) / dpr, round(rect.top() * dpr) / dpr
    if icon is not None and not icon.isNull():
        painter.drawPixmap(QPointF(x, y), icon)
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.WELL))
    painter.drawRoundedRect(QRectF(x, y, ROW_ICON_PX, ROW_ICON_PX), ROW_ICON_RADIUS, ROW_ICON_RADIUS)


def paint_update_button(painter: QPainter, rect, widget: QWidget, hover: bool, enabled: bool) -> None:
    """.vh-update-btn: --panel-2 fill, 1px --warn border (--muted while
    hovered: button:hover:not(:disabled)), --radius corners, a bold "↑" in
    --warn. Disabled: half opacity, no hover look. The caller saves/restores
    the painter."""
    r = QRectF(rect)
    radius = min(theme.RADIUS, r.height() / 2) - 0.5
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        painter.setOpacity(painter.opacity() * DISABLED_BUTTON_OPACITY)
    painter.setPen(QPen(QColor(theme.MUTED if hover and enabled else theme.WARN), 1))
    painter.setBrush(QColor(theme.PANEL_2))
    painter.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.setFont(bold_font(widget.font()))
    painter.setPen(QColor(theme.WARN))
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, UPDATE_GLYPH)


def mix_color(a: str, b: str, t: float) -> QColor:
    """Color `a` at t = 0 .. `b` at t = 1, per channel (alpha included)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * t) for x, y in zip(
        (ca.red(), ca.green(), ca.blue(), ca.alpha()), (cb.red(), cb.green(), cb.blue(), cb.alpha()))))


def paint_toggle(painter: QPainter, rect, on: bool, hover: bool, enabled: bool, t: float | None = None) -> None:
    """.vh-toggle: a 34x18 pill - --border fill and border when off, --accent
    when on (.vh-toggle.on; --accent-hover while hovered, as a primary
    button); the hover look when off is a --muted border (button:hover).
    The white 14px knob sits 2px in from the left (off) or the right (on).
    Disabled: half opacity, no hover look. `t`: the knob's position mid-slide,
    0 (off) .. 1 (on), fill and border blended to match; None = `on`'s end
    (0 and 1 paint exactly the static look). The caller saves/restores."""
    r = QRectF(rect)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        painter.setOpacity(painter.opacity() * DISABLED_BUTTON_OPACITY)
    hover = hover and enabled
    if t is None:
        t = 1.0 if on else 0.0
    on_fill = theme.ACCENT_HOVER if hover else theme.ACCENT
    painter.setPen(QPen(mix_color(theme.MUTED if hover else theme.BORDER, on_fill, t), 1))
    painter.setBrush(mix_color(theme.BORDER, on_fill, t))
    radius = r.height() / 2 - 0.5
    painter.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    left, right = r.left() + 2, r.right() - 2 - KNOB + 1
    knob_x = left + (right - left) * t
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(QRectF(knob_x, r.top() + 2, KNOB, KNOB))


def paint_row_content(painter: QPainter, rect, info: RowInfo, view: "BepInExModListView",
                      hover: str | None, enabled: bool, toggle_t: float | None = None) -> None:
    """The two text lines and the right-end pieces of a row painted at item
    rect `rect` (the card itself is already there, from the base paint).
    The icon tile sits at the left (icon_rect); the text block takes the
    card's width from ROW_PAD past the tile to ROW_PAD before the pieces at
    the right; the name is elided before
    its marks, the marks never shrink (.vh-row-name: the spans are
    flex: none, the name has the ellipsis). `toggle_t`: the toggle's knob
    mid-slide (paint_toggle's t). The caller saves/restores."""
    viewport = view.viewport().rect()
    card = card_rect(rect, viewport, view)
    pieces = layout_row(info, rect, viewport, view)
    dpr = view.devicePixelRatioF()
    tile = icon_rect(card)
    painter.save()
    paint_row_icon(painter, tile, info.icon, dpr)
    painter.restore()
    left = tile.right() + 1 + ROW_PAD  # the text block, right of the icon (was card.left() + ROW_PAD)
    right = card.right() - ROW_PAD
    if pieces:
        right = min(r.left() for r in pieces.values()) - 1 - ROW_PAD
    width = max(0, right - left + 1)

    name_font = QFont(view.font())
    nm = QFontMetrics(name_font)
    mfont = meta_font(view)
    mm = QFontMetrics(mfont)
    total = nm.height() + LINE_GAP + mm.height()
    top = card.top() + (card.height() - total) // 2

    marks: list[tuple[str, str]] = []
    if info.warn:
        marks.append((WARN_MARK, theme.WARN))
    if info.error:
        marks.append((ERROR_MARK, theme.DANGER))
    marks_w = len(marks) * (MARK_PX + NAME_GAP)
    pills = [(t, c) for t, c, on in ((DISABLED_TEXT, theme.WARN, info.disabled),
                                     (DEPRECATED_TEXT, theme.DANGER, info.deprecated),
                                     (FILES_MISSING_TEXT, theme.WARN, info.files_missing)) if on]
    bfont = badge_font(view)
    x = left
    for text, color in pills:  # before the name, never shrunk (like the marks)
        w = badge_width(bfont, text)
        if x + w > left + width:  # 0.6.27: a pill that doesn't fit is left out, never painted over the controls
            break
        paint_row_badge(painter, QRectF(x, top + (nm.height() - BADGE_HEIGHT) / 2, w, BADGE_HEIGHT), bfont, text, color)
        x += w + NAME_GAP
    name_w = max(0, left + width - x - marks_w)
    if info.disabled:
        name_font.setStrikeOut(True)
    name = nm.elidedText(info.name, Qt.TextElideMode.ElideRight, name_w)
    painter.setFont(name_font)
    painter.setPen(QColor(theme.MUTED if info.disabled else theme.TEXT))
    line1 = QRect(x, top, name_w, nm.height())
    painter.drawText(line1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
    x += nm.horizontalAdvance(name) + NAME_GAP
    for mark, color in marks:
        painter.drawPixmap(QPointF(x, top + (nm.height() - MARK_PX) // 2), icons.pixmap(mark, color, MARK_PX, dpr))
        x += MARK_PX + NAME_GAP

    painter.setFont(mfont)
    painter.setPen(QColor(theme.WARN if info.meta_warn else theme.MUTED))
    meta = mm.elidedText(info.meta, Qt.TextElideMode.ElideRight, width)
    line2 = QRect(left, top + nm.height() + LINE_GAP, width, mm.height())
    painter.drawText(line2, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, meta)

    if PINNED in pieces:
        painter.setFont(tag_font(view))
        painter.setPen(QColor(theme.MUTED))
        painter.drawText(pieces[PINNED], Qt.AlignmentFlag.AlignCenter, PINNED_TEXT)
    if UPDATE in pieces:
        painter.save()
        paint_update_button(painter, pieces[UPDATE], view, hover == UPDATE, enabled and not info.busy)
        painter.restore()
    if TOGGLE in pieces:
        painter.save()
        paint_toggle(painter, pieces[TOGGLE], bool(info.toggle), hover == TOGGLE, enabled, toggle_t)
        painter.restore()


class BepInExRowDelegate(ModRowDelegate):
    """ModRowDelegate with the taller two-line card (class docstring): the
    base paint draws the card with no text, then the row's content and
    controls go on top under the same clip / opacity."""

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        _left, top, _right, bottom = theme.row_margins(self._view)
        return QSize(size.width(), CARD_HEIGHT + top + bottom)

    def initStyleOption(self, option, index) -> None:
        super().initStyleOption(option, index)
        option.text = ""  # the two lines are painted by _paint_card (the drag pill still reads the model's text)

    def _paint_card(self, painter, opt, index, clip, faded: bool, mark: str | None) -> None:
        super()._paint_card(painter, opt, index, clip, faded, mark)
        view = self._view
        info = view.row_info_at(index.row()) if index.isValid() else None
        if info is None:
            return
        painter.save()
        if clip is not None:
            painter.setClipRect(clip, Qt.ClipOperation.IntersectClip)
        opacity = DIMMED_ROW_OPACITY if mark == MARK_DIM else DRAGGED_ROW_OPACITY if faded else None
        if opacity is not None:
            painter.setOpacity(opacity)
        if info.pinned and mark != MARK_MATCH:
            # .vh-row.pinned: inset 3px 0 0 var(--accent), the match bar's shape; on the card, past the rail's gutter
            paint_match_bar(painter, opt.rect.adjusted(theme.row_margins(view)[0] - theme.ROW_MARGINS[0], 0, 0, 0))
        t = view.toggle_t(index.row())
        paint_row_content(painter, opt.rect, info, view, view.control_hover_kind(index.row()), view.controls_enabled(), t)
        if view.property("rail") is True:
            # the row's rail node, under the same clip / opacity (the dragged row's faded slot, the slide);
            # mid toggle slide it keeps the old state, switching as the knob lands (designer, M4)
            live = (info.toggle is not False) != (t is not None)
            state = painters.RAIL_TERMINAL if info.pinned else painters.RAIL_LIVE if live else painters.RAIL_OFF
            painter.save()
            painters.paint_rail_node(painter, opt.rect, state)  # switches the painter to device space
            painter.restore()
        painter.restore()

    def helpEvent(self, event, view, option, index) -> bool:
        """Over a control: its own tooltip (control_tip); else the row's."""
        if event is not None and event.type() == QEvent.Type.ToolTip:
            tip = self._view.control_tip(event.pos())
            if tip is not None:
                from PySide6.QtWidgets import QToolTip

                text, rect = tip
                QToolTip.showText(event.globalPos(), text, self._view.viewport(), rect)
                return True
        return super().helpEvent(event, view, option, index)


class BepInExModListView(ModListView):
    """ModListView with BepInExRowDelegate's rows and the per-row controls
    (class docstring). `row_info` (mod id -> RowInfo, or None for an id the
    screen doesn't know) describes each row; `controls_enabled` (() -> bool;
    None = always) gates every control while the screen is busy;
    `on_update(mod id)` / `on_toggle(mod id, on)` take the clicks. The other
    keyword arguments are ModListView's own."""

    def __init__(
        self,
        display_name: Callable[[str], str],
        parent: QWidget | None = None,
        *,
        row_info: Callable[[str], RowInfo | None],
        controls_enabled: Callable[[], bool] | None = None,
        on_update: Callable[[str], None] | None = None,
        on_toggle: Callable[[str, bool], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(display_name, parent, **kwargs)
        self._row_info = row_info
        self._controls_enabled = controls_enabled
        self._on_update = on_update
        self._on_toggle = on_toggle
        self._control_hover: tuple[int, str] | None = None  # (row, kind) under the pointer
        # The toggle slide: mod id -> (start, monotonic s; the state it slides to). Only a single
        # toggle click adds one (_release_issue); the timer runs only while this is non-empty.
        self._toggle_anim: dict[str, tuple[float, bool]] = {}
        self._toggle_timer = QTimer(self)
        self._toggle_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._toggle_timer.setInterval(TOGGLE_FRAME_MS)
        self._toggle_timer.timeout.connect(self._on_toggle_tick)
        self.mod_model.modelReset.connect(self.cancel_toggle_slides)
        self.setItemDelegate(BepInExRowDelegate(self))
        # Hover moves over the rows, for the controls' hand cursor / hover look.
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)

    # ---- rows ----
    def row_info_at(self, row: int) -> RowInfo | None:
        mod_id = self.mod_model.id_at(row)
        return self._row_info(mod_id) if mod_id is not None else None

    def controls_enabled(self) -> bool:
        return self._controls_enabled is None or bool(self._controls_enabled())

    def is_pinned_row(self, row: int) -> bool:
        info = self.row_info_at(row)
        return info is not None and info.pinned

    # ---- the painted controls (mod_list.py's issue-icon / Subscribe machinery) ----
    def control_rects(self, info: RowInfo, rect) -> list[tuple[str, QRect]]:
        """(kind, rect) of the row's clickable controls: UPDATE and / or TOGGLE."""
        pieces = layout_row(info, rect, self.viewport().rect(), self)
        return [(kind, r) for kind, r in pieces.items() if kind in (UPDATE, TOGGLE)]

    def control_at(self, pos) -> tuple[int, str] | None:
        """(row, kind) of the control under viewport point `pos`, or None -
        always None while rows are only previewed (a drag under way)."""
        if pos is None or self.drag_preview is not None:
            return None
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        info = self.row_info_at(index.row())
        if info is None:
            return None
        for kind, r in self.control_rects(info, self.visualRect(index)):
            if r.contains(pos):
                return index.row(), kind
        return None

    def control_tip(self, pos) -> tuple[str, QRect] | None:
        """(tooltip text, control rect) for the control under `pos`, or None."""
        hit = self.control_at(pos)
        if hit is None:
            return None
        row, kind = hit
        info = self.row_info_at(row)
        if info is None:
            return None
        rect = dict(self.control_rects(info, self.visualRect(self.mod_model.index(row, 0))))[kind]
        if kind == UPDATE:
            text = info.update_tip or f"Update {info.name}"
        else:
            text = f"{'Disable' if info.toggle else 'Enable'} {info.name}"
        return text, rect

    def control_hover_kind(self, row: int) -> str | None:
        """For the delegate: the kind of `row`'s control under the pointer
        (its hover look); None mid-drag or while the controls are disabled."""
        if self._control_hover is None or self.drag_preview is not None or not self.controls_enabled():
            return None
        return self._control_hover[1] if self._control_hover[0] == row else None

    def _update_issue_cursor(self, pos) -> None:
        """The hand cursor over a control (button { cursor: pointer }) and the
        hover look (a repaint when it changes); `pos` None: the pointer left."""
        hit = self.control_at(pos) if pos is not None and self._drag_state is None else None
        over = hit is not None and self.controls_enabled()
        if over != self._issue_hover:
            self._issue_hover = over
            if over:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.viewport().unsetCursor()
        hover = hit if over else None
        if hover != self._control_hover:
            self._control_hover = hover
            self.viewport().update()

    def viewportEvent(self, event) -> bool:
        kind = event.type()
        if kind in (QEvent.Type.HoverEnter, QEvent.Type.HoverMove):
            self._update_issue_cursor(event.position().toPoint())
        elif kind == QEvent.Type.HoverLeave:
            self._update_issue_cursor(None)
        return super().viewportEvent(event)

    def _release_issue(self, event) -> None:
        """The left release after a control press (ModListView._press_issue):
        a click if it's still over the same control of the same mod."""
        (row, mod_id, kind), self._issue_press = self._issue_press, None
        same = self.control_at(event.position().toPoint()) == (row, kind) and self.mod_model.id_at(row) == mod_id
        if not same:
            log(f"{kind} control: press on {mod_id} released elsewhere, nothing done")
            return
        if not self.controls_enabled():
            log(f"{kind} control: click on {mod_id} in {self.name}, but the controls are disabled (busy)")
            return
        info = self.row_info_at(row)
        if info is None:
            return
        if kind == UPDATE:
            if info.busy or self._on_update is None:
                log(f"update button: click on {mod_id} in {self.name} ignored (already updating)")
                return
            log(f"update button: click on {mod_id} in {self.name}")
            self._on_update(mod_id)
        elif kind == TOGGLE and info.toggle is not None and self._on_toggle is not None:
            log(f"toggle: click on {mod_id} in {self.name} -> {'on' if not info.toggle else 'off'}")
            if theme.animations_enabled():  # asked at every click, never cached
                self._toggle_anim[mod_id] = (time.monotonic(), not info.toggle)
                self._toggle_timer.start()
            self._on_toggle(mod_id, not info.toggle)

    # ---- the toggle slide (phase 4 M4) ----
    def toggle_t(self, row: int) -> float | None:
        """For the delegate: `row`'s toggle knob mid-slide (paint_toggle's t),
        or None = the static look - no slide, the click's change not applied
        (a refused toggle), or the controls disabled."""
        mod_id = self.mod_model.id_at(row)
        entry = self._toggle_anim.get(mod_id) if mod_id is not None else None
        info = self.row_info_at(row) if entry is not None else None
        if info is None or info.toggle != entry[1] or not self.controls_enabled():
            return None
        p = _EASE.valueForProgress(min(1.0, max(0.0, (time.monotonic() - entry[0]) * 1000 / theme.MOTION_FAST)))
        return p if entry[1] else 1.0 - p

    def _on_toggle_tick(self) -> None:
        """A frame: repaint each sliding toggle's rect; a finished (or vanished)
        slide is dropped and its whole row repainted once (the rail node)."""
        now = time.monotonic()
        viewport = self.viewport()
        ids = self.mod_model.ids()
        for mod_id, (start, _on) in list(self._toggle_anim.items()):
            row = ids.index(mod_id) if mod_id in ids else None
            rect = self.visualRect(self.mod_model.index(row, 0)) if row is not None else None
            info = self.row_info_at(row) if row is not None else None
            pieces = layout_row(info, rect, viewport.rect(), self) if info is not None else {}
            if (now - start) * 1000 >= theme.MOTION_FAST or TOGGLE not in pieces:
                del self._toggle_anim[mod_id]
                if rect is not None:
                    viewport.update(rect)
            else:
                viewport.update(pieces[TOGGLE])
        if not self._toggle_anim:
            self._toggle_timer.stop()

    def cancel_toggle_slides(self) -> None:
        """Drops every slide (drag start, model reset, hidden): static look now."""
        if self._toggle_anim:
            self._toggle_anim.clear()
            self.viewport().update()
        self._toggle_timer.stop()

    def hideEvent(self, event) -> None:
        self.cancel_toggle_slides()
        super().hideEvent(event)

    # ---- drag-reorder: the pinned row stays first ----
    def _start_drag(self, pos: QPoint, global_pos: QPoint) -> None:
        self.cancel_toggle_slides()
        if self._drag_row is not None and self.is_pinned_row(self._drag_row):
            self._end_drag("cancelled", reason="the pinned framework row isn't draggable")
            return
        super()._start_drag(pos, global_pos)

    def _drag_target_row(self, pos: QPoint) -> int | None:
        target = super()._drag_target_row(pos)
        if target == 0 and self.is_pinned_row(0):
            return 1 if self.mod_model.rowCount() > 1 else None  # nothing lands above the framework row
        return target
