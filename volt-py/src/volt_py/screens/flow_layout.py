"""FlowLayout: a wrapping, row-centered QLayout.

Port of the CSS flex-wrap grid used by the game-selection screen
(`.game-select-grid`: `display: flex; flex-wrap: wrap; gap: 28px;
justify-content: center; max-width: 1440px`). Items flow left to right,
wrap to a new row when the next one would not fit, and each finished row is
centered horizontally in the layout's rect. Reuse it for any future screen
that needs the same reflow behavior.

Two sizing modes:

- Default (no item_* arguments): every item is placed at its sizeHint(),
  top-aligned in its row - CSS `flex: 0 0 auto`.
- Flex mode (`item_basis_width` given): the port of CSS
  `flex: 1 1 <basis>; min-width: <min>; max-width: <max>` applied to every
  item, for the uniform case where all items share the same basis/min/max
  (true for the game grid's tiles; mixed flex items are not supported).
  1. Rows are broken using each item's basis clamped to [min, max] (CSS's
     hypothetical main size) plus the gaps - never using the item's
     sizeHint width.
  2. Each row's free space (`row width - (n * basis + (n - 1) * gap)`, where
     row width is the wrap width below) is shared equally by its n items,
     and each resulting width is clamped to [min, max]. With identical
     items they all clamp together, so CSS's iterative freeze-and-
     redistribute loop reduces to this single step. Any space left over
     after clamping at max becomes centering margin (justify-content).
  3. Items are resized to that width (height stays their sizeHint height).
  Widths are whole pixels (floored); CSS uses fractional px, so a row can
  be up to n-1 px narrower than Chromium's, the difference going to the
  centering margins.
  Because step 1 wraps by basis, a row always has free space >= 0 unless it
  holds a single item wider than the row, so in practice items grow
  (basis -> max) and only a lone item in a row narrower than the basis
  ever shrinks (toward min, never below it).

`center_rows=False` places each row from the left edge instead of centering
it (CSS `justify-content: flex-start`, the flex-wrap default) - e.g. the
Settings window's wrapping radio row (screens/settings_window.py).

`max_row_width` (optional) caps how wide a row may grow before it wraps -
the port of the grid's CSS `max-width`. Rows stay centered in the layout's
full rect, which is visually the same as a max-width container centered in
its parent with centered rows inside it. Done here rather than via the
container widget's maximumWidth so the layout can be nested with addLayout()
(no container widget, so its items' drop shadows aren't clipped at a
container edge) and so heightForWidth() always wraps at the same width
setGeometry() will use.

Supports height-for-width, so a QScrollArea(widgetResizable=True) or a
QBoxLayout holding it grows taller as the rows wrap.
"""

import math

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget

_Row = tuple[list[tuple[QLayoutItem, QSize]], int, int]  # (items + hints, wrap width, height)


class FlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        horizontal_spacing: int = 28,
        vertical_spacing: int = 28,
        max_row_width: int | None = None,
        item_basis_width: int | None = None,
        item_min_width: int | None = None,
        item_max_width: int | None = None,
        center_rows: bool = True,
    ) -> None:
        super().__init__(parent)
        # Python-side item list: QLayout keeps no item storage of its own.
        self._items: list[QLayoutItem] = []
        self.horizontal_spacing = horizontal_spacing
        self.vertical_spacing = vertical_spacing
        self.max_row_width = max_row_width
        self.center_rows = center_rows  # False: rows start at the left edge (justify-content: flex-start)
        # Flex mode (module docstring) when a basis is given; min/max only
        # apply in flex mode and default to unbounded.
        self.item_basis_width = item_basis_width
        self.item_min_width = item_min_width
        self.item_max_width = item_max_width
        # Explicit: a top-level QLayout would otherwise take the style's
        # default margins (~9-11px); spacing around the grid is the caller's.
        self.setContentsMargins(0, 0, 0, 0)

    # ---- QLayout item storage ----

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    # ---- sizing ----

    def expandingDirections(self) -> Qt.Orientation:
        # Neither direction: the rows are only as wide as their items.
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self) -> QSize:
        # Preferred: everything on one row at wrap width (capped at
        # max_row_width, then as tall as the wrapped rows need at that width).
        margins = self.contentsMargins()
        visible = [item for item in self._items if not item.isEmpty()]
        width = sum(self._wrap_width_of(item.sizeHint()) for item in visible)
        width += self.horizontal_spacing * max(0, len(visible) - 1)
        if self.max_row_width is not None:
            width = min(width, self.max_row_width)
        width += margins.left() + margins.right()
        return QSize(width, self.heightForWidth(width))

    def minimumSize(self) -> QSize:
        # One item per row: the widest/tallest item. In default mode items
        # are placed at their sizeHint, so that (not just minimumSize) sets
        # the floor; in flex mode a lone item can shrink to item_min_width.
        size = QSize(0, 0)
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if self._flex:
                floor = self.item_min_width if self.item_min_width is not None else self._wrap_width_of(hint)
                size = size.expandedTo(QSize(floor, hint.height()))
            else:
                size = size.expandedTo(item.minimumSize()).expandedTo(hint)
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, apply=True)

    # ---- flex helpers ----

    @property
    def _flex(self) -> bool:
        return self.item_basis_width is not None

    def _clamp(self, width: int) -> int:
        if self.item_max_width is not None:
            width = min(width, self.item_max_width)
        if self.item_min_width is not None:
            width = max(width, self.item_min_width)
        return width

    def _wrap_width_of(self, hint: QSize) -> int:
        """The width an item counts as when breaking rows: its sizeHint in
        default mode; in flex mode the basis clamped to [min, max] (CSS's
        hypothetical main size)."""
        if self._flex:
            return self._clamp(self.item_basis_width)
        return hint.width()

    def _resolved_width(self, count: int, basis_row_width: int, wrap_width: int) -> int:
        """Flex mode: every item's width in a row of `count` items whose
        basis widths + gaps add up to `basis_row_width` (step 2)."""
        # The basis as clamped for row breaking. Identical to CSS's flex base
        # size whenever the basis lies within [min, max] (the only case this
        # layout is meant for; the game grid's 300 in [220, 336]).
        basis = self._clamp(self.item_basis_width)
        free = wrap_width - basis_row_width
        return self._clamp(math.floor(basis + free / count))

    # ---- the actual flow ----

    def _do_layout(self, rect: QRect, apply: bool) -> int:
        """Break the items into rows that fit, place (and in flex mode size)
        them if `apply`, and return the total height used, margins included."""
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        wrap_width = area.width()
        if self.max_row_width is not None:
            wrap_width = min(wrap_width, self.max_row_width)

        rows: list[_Row] = []
        row: list[tuple[QLayoutItem, QSize]] = []
        row_width = row_height = 0
        for item in self._items:
            if item.isEmpty():  # hidden widget
                continue
            hint = item.sizeHint()
            w = self._wrap_width_of(hint)
            needed = w if not row else row_width + self.horizontal_spacing + w
            if row and needed > wrap_width:
                rows.append((row, row_width, row_height))
                row, row_height = [], 0
                needed = w
            row.append((item, hint))
            row_width = needed
            row_height = max(row_height, hint.height())
        if row:
            rows.append((row, row_width, row_height))

        y = area.y()
        for index, (row_items, basis_row_width, height) in enumerate(rows):
            if index:
                y += self.vertical_spacing
            if apply:
                if self._flex:
                    item_width = self._resolved_width(len(row_items), basis_row_width, wrap_width)
                    placed = [(item, QSize(item_width, hint.height())) for item, hint in row_items]
                else:
                    placed = row_items
                width = sum(size.width() for _, size in placed) + self.horizontal_spacing * (len(placed) - 1)
                # justify-content: center (or flex-start without center_rows).
                # A lone item wider than the area stays left-aligned (visible)
                # rather than centering off-screen.
                x = area.x() + (max(0, (area.width() - width) // 2) if self.center_rows else 0)
                for item, size in placed:
                    item.setGeometry(QRect(QPoint(x, y), size))
                    x += size.width() + self.horizontal_spacing
            y += height
        return y - area.y() + margins.top() + margins.bottom()
