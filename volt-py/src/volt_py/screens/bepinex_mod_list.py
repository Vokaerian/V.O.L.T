"""The Thunderstore/BepInEx manager's mod-list rows (THUNDERSTORE.md §3; the
signed-off Valheim main-screen mockup's .vh-row / .vh-toggle /
.vh-update-btn, https://claude.ai/artifact/KeNe4nnwPVmCgfxrpbXBCZ).
Game-agnostic: Valheim's screen uses it today, the next BepInEx game
(Lethal Company, R.E.P.O.) reuses it as-is.

Built on screens/mod_list.py's ModListView / ModRowDelegate - the model,
search (query + eye), click-to-deselect, double-click moves and the
drag-reorder preview/animation are all inherited unchanged. What differs:

  - Rows are CARD_HEIGHT (54px) tall, two lines: the mod's display name on
    line 1 (13px, --text), a "⚠" in --warn after it when an update is
    available and a "✕" in --danger when a dependency is missing (its
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

The screen supplies everything per row through `row_info` (mod id ->
RowInfo) at paint / hit-test time - nothing is stored here, as with
mod_list.py's `decor` callable - and takes the clicks through `on_update`
(mod id) and `on_toggle` (mod id, new state).
"""

from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from volt_py import theme
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
NAME_GAP = 6  # .vh-row-name gap: name | ⚠ | ✕
ACTIONS_GAP = 8  # .vh-row-actions gap: update button | toggle
TOGGLE_W, TOGGLE_H = 34, 18  # .vh-toggle
KNOB = 14  # .vh-toggle-knob; 1px inside the 1px border: 2px from the pill's edge
UPDATE_SIZE = 24  # .vh-update-btn
TAG_FONT_PX = 11  # .tag font-size ("Pinned")

UPDATE = "update"
TOGGLE = "toggle"
PINNED = "pinned"  # the Pinned tag's slot: laid out with the controls, never clickable
WARN_GLYPH = "⚠"
ERROR_GLYPH = "✕"
UPDATE_GLYPH = "↑"
PINNED_TEXT = "Pinned"
DISABLED_TEXT = "Disabled"  # the status pills before the name (RowInfo.disabled / .deprecated)
DEPRECATED_TEXT = "Deprecated"


class RowInfo(NamedTuple):
    """One row, as the screen describes it (row_info(mod id))."""

    name: str  # line 1
    meta: str  # line 2 ("v2.30.2 · Updated 12d ago", "v2.30.2 · update available", ...)
    meta_warn: bool = False  # line 2 in --warn (an update is available)
    pinned: bool = False  # the framework row: accent bar, Pinned tag, no toggle, not draggable
    toggle: bool | None = None  # the toggle's state; None = no toggle on this row
    update: bool = False  # paint the update button (an update is available)
    warn: bool = False  # "⚠" after the name
    error: str | None = None  # "✕" after the name, with this tooltip (a missing dependency)
    busy: bool = False  # this mod's update is in flight: its button disabled
    update_tip: str = ""  # the update button's tooltip ("Update Jotunn to 2.31.0")
    disabled: bool = False  # "Disabled" pill + muted struck-through name (an Active row toggled off)
    deprecated: bool = False  # "Deprecated" pill (Thunderstore marks the package deprecated)


def card_rect(rect, viewport) -> QRect:
    """The row card inside item rect `rect`: clipped to the viewport's right
    edge (a list-mode row rect is as wide as the widest row), then inset by
    the ::item margins (theme.ROW_MARGINS), as ModListView._card_rect."""
    left, top, right, bottom = theme.ROW_MARGINS
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
    card = card_rect(rect, viewport)
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


def paint_toggle(painter: QPainter, rect, on: bool, hover: bool, enabled: bool) -> None:
    """.vh-toggle: a 34x18 pill - --border fill and border when off, --accent
    when on (.vh-toggle.on; --accent-hover while hovered, as a primary
    button); the hover look when off is a --muted border (button:hover).
    The white 14px knob sits 2px in from the left (off) or the right (on).
    Disabled: half opacity, no hover look. The caller saves/restores."""
    r = QRectF(rect)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        painter.setOpacity(painter.opacity() * DISABLED_BUTTON_OPACITY)
    hover = hover and enabled
    if on:
        fill = theme.ACCENT_HOVER if hover else theme.ACCENT
        border = fill
    else:
        fill = theme.BORDER
        border = theme.MUTED if hover else theme.BORDER
    painter.setPen(QPen(QColor(border), 1))
    painter.setBrush(QColor(fill))
    radius = r.height() / 2 - 0.5
    painter.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    knob_x = r.right() - 2 - KNOB + 1 if on else r.left() + 2
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffffff"))
    painter.drawEllipse(QRectF(knob_x, r.top() + 2, KNOB, KNOB))


def paint_row_content(painter: QPainter, rect, info: RowInfo, view: "BepInExModListView",
                      hover: str | None, enabled: bool) -> None:
    """The two text lines and the right-end pieces of a row painted at item
    rect `rect` (the card itself is already there, from the base paint).
    The text block takes the card's width less ROW_PAD each side and the
    pieces at the right (ROW_PAD before them); the name is elided before
    its marks, the marks never shrink (.vh-row-name: the spans are
    flex: none, the name has the ellipsis). The caller saves/restores."""
    viewport = view.viewport().rect()
    card = card_rect(rect, viewport)
    pieces = layout_row(info, rect, viewport, view)
    left = card.left() + ROW_PAD
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
        marks.append((WARN_GLYPH, theme.WARN))
    if info.error:
        marks.append((ERROR_GLYPH, theme.DANGER))
    mark_font = bold_font(name_font)
    km = QFontMetrics(mark_font)
    marks_w = sum(km.horizontalAdvance(g) + NAME_GAP for g, _ in marks)
    pills = [(t, c) for t, c, on in ((DISABLED_TEXT, theme.WARN, info.disabled),
                                     (DEPRECATED_TEXT, theme.DANGER, info.deprecated)) if on]
    bfont = badge_font(view)
    x = left
    for text, color in pills:  # before the name, never shrunk (like the marks)
        w = badge_width(bfont, text)
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
    painter.setFont(mark_font)
    for glyph, color in marks:
        w = km.horizontalAdvance(glyph)
        painter.setPen(QColor(color))
        painter.drawText(QRect(x, top, w, nm.height()), Qt.AlignmentFlag.AlignCenter, glyph)
        x += w + NAME_GAP

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
        paint_toggle(painter, pieces[TOGGLE], bool(info.toggle), hover == TOGGLE, enabled)
        painter.restore()


class BepInExRowDelegate(ModRowDelegate):
    """ModRowDelegate with the taller two-line card (class docstring): the
    base paint draws the card with no text, then the row's content and
    controls go on top under the same clip / opacity."""

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        _left, top, _right, bottom = theme.ROW_MARGINS
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
            paint_match_bar(painter, opt.rect)  # .vh-row.pinned: inset 3px 0 0 var(--accent), the match bar's shape
        paint_row_content(painter, opt.rect, info, view, view.control_hover_kind(index.row()), view.controls_enabled())
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
            self._on_toggle(mod_id, not info.toggle)

    # ---- drag-reorder: the pinned row stays first ----
    def _start_drag(self, pos: QPoint, global_pos: QPoint) -> None:
        if self._drag_row is not None and self.is_pinned_row(self._drag_row):
            self._end_drag("cancelled", reason="the pinned framework row isn't draggable")
            return
        super()._start_drag(pos, global_pos)

    def _drag_target_row(self, pos: QPoint) -> int | None:
        target = super()._drag_target_row(pos)
        if target == 0 and self.is_pinned_row(0):
            return 1 if self.mod_model.rowCount() > 1 else None  # nothing lands above the framework row
        return target
