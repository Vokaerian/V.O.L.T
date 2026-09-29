"""The mod-list panes (ModList.jsx): Qt model/view pieces behind the RimWorld
main screen's Inactive and Active lists.

  ModListModel    a pane's real, ordered mod ids (Active: the load order)
  PaneSearch      a pane's search: query, eye toggle (dim), the matching ids
  DragPreview     a drag in progress, as plain ints (start row, target row)
  SlideAnimation  the preview's animation: rows sliding to their new slots
  ModRowDelegate  paints each id as a .row card, the search's dim/match
                  marks, and the drag preview
  ModListView     the list: click-to-deselect, search; Active (draggable)
                  adds drag-reorder

PaneSearch, DragPreview and SlideAnimation (with Slide) are plain Python, no
Qt: the search's and the drag's whole state. ModListView only drives them
(input, row hiding, a frame timer, repaints).

Search (ModList.jsx query/dim, lists.js modMatches) never touches the model
either: ModListModel always holds the pane's full, ordered list (mod_ids(),
dirty tracking, Save/Push and the drag all rely on that). Hiding mode (a
query, eye closed - the default) hides the non-matching rows in the view
(QListView.setRowHidden), so view rows stay model rows one to one and
nothing needs remapping; drag-reorder is off while rows are hidden
(ModList.jsx dragEnabled = sortable && !hiding). Dim mode (eye open) hides
nothing: the delegate fades non-matches and puts the accent bar on matches,
and drag works as usual.

The model holds ids only; names come from the screen's scanned mods through
the `display_name` callable, so nothing is duplicated. The row-card look is
theme.py's QListView[modList="true"]::item rules, painted by the delegate's
base QStyledItemDelegate.paint (the same path the old QListWidget panes used).

Drag-reorder (Active only) follows ModList.jsx / dnd-kit: while a drag is
under way the model is never touched - the view keeps a DragPreview (where
the dragged row would land) and the delegate paints that preview over the
unchanged rows; the drop is the one ModListModel.move_row call (onDragEnd's
arrayMove). Esc / focus loss / anything abnormal ends the drag with no
change at all.

When the preview's target changes, the rows it moves slide to their new slots
(SlideAnimation, SLIDE_MS ease-out, retargeted mid-slide without a jump or a
slow restart) instead of snapping. Animation only changes where the delegate
paints a row's content; it never touches the model, and the drop / cancel are
exactly as without it (the model's order shows at once, even mid-slide).

Row decorations (ModList.jsx RowLabel / Row; the flags are
mod_decorations.RowDecor, computed by the screen through the model's `decor`
callable, never stored here): the official "L" badge (.row-badge) after the
color swatch, the outdated name in --danger (.row-name.outdated, selected
or not), and the selected mod's dependency / dependent tint
(.row.dependency / .row.dependent: the card's background replaced by the
tint, plus inset bars). ModRowDelegate.initStyleOption puts the badge in the
item's decoration (so the base paint lays the name out after it, as it does
after the swatch) and the name color in the option's palette; a tinted row
is flagged with the (otherwise unused) Alternate feature, which theme.py's
::item:alternate rule turns into a transparent card, so the tint the
delegate paints underneath shows through (_paint_card). The drag pill draws
the badge and the red name itself (drag_pill_pixmap), never the tint. The
row's tooltip (ModList.jsx Row's title) is the model's ToolTipRole, from the
`tooltip` callable.

Validation marks (RowDecor.warning / error / conflict; ModList.jsx RowIssues
and .row.conflict): an active hard conflict gets the outdated red name (in the
drag pill too) plus a 1px --warn outline on the card, painted last so it
stacks over the dependency tint and bars (paint_conflict_outline). The Active
pane's issue icons - the warning triangle, then the red cross, rightmost - sit
at the right end of the card (.row-issues' margin-left: auto), inside the
row's 8px padding and clipped to the viewport like the drag pill's card, so
they stay visible when a long name widens the list; a row with icons has its
name elided before them (ModRowDelegate._text_right). Each icon has its own
tooltip (that severity's issues, validation_window.issue_summary, one per
line; ModRowDelegate.helpEvent) and click (ModListView: `on_show_issue` with
that severity's first issue key). An icon press is taken whole by the icon -
no selection, no drag, no double-click move - and opens on a release over the
same icon, like a button. Only a view given `on_show_issue` paints and
hit-tests icons (the Active pane); the icons follow the content mid-drag like
the other decorations.

Pending rows (RowDecor.pending / downloading; ModList.jsx RowLabel / RowView
for a "not found" row whose id is a Workshop id): a pending row's card gets
a dashed --border outline (paint_pending_outline, an outline like the
conflict one, so nothing shifts; a conflict's outline wins, as .row.conflict
comes later in styles.css), its name (the screen's display_name: the
Workshop title when known, else the id) in the normal color with a muted
11px "(pending)" after it (paint_row_suffix, on the name's baseline; the
suffix is elided first when the row is too narrow, as it sits inside
.row-name's ellipsis), and the Subscribe button (.row-subscribe) at the
card's right end - painted (paint_subscribe_button), not a widget, and
hit-tested exactly like the issue icons: the same press state
(_issue_press, kind SUBSCRIBE), taken whole, fires `on_subscribe(mod id)` on
a release over the same button, hand cursor, its own tooltip, and a --muted
border while hovered. Only a view given `on_subscribe` paints and hit-tests
it (the Active pane). `subscribe_enabled()` false (ModList.jsx disabled=
{!canSubscribe}: Steam-client mode with Steam unavailable) paints it at half
opacity (button:disabled) with no hover look, no hand cursor and no click -
the tooltip still says why. A downloading row is faded (DOWNLOADING_ROW_OPACITY),
its name red with a muted "⟳ downloading…", no outline and no button.
A plain not-found row (RowDecor.not_found without pending / downloading: an
Active id that didn't scan and isn't a Workshop id, kept by the screen's
_show_lists as Electron's reconcileLists keeps it) is RowLabel's other
missing case: the same red name and the same muted suffix, reading
"(not found)" - no fade, no outline, no button. Only Active can hold one;
Inactive is built from the scanned mods.

.dds leftovers (RowDecor.dds_leftover; ModList.jsx RowLabel's
.row-badge.dds-leftover): a muted ".dds" badge - the "L" badge's box with
--muted border and text - one .row gap right after the name, never shrunk
(flex: none): the name is elided to leave room for it (ModRowDelegate
._layout_badge), and the badge is painted after the base paint. Not the
decoration slot, which stays the official badge's (before the name). The
drag pill shows it the same way.

Mod warnings (RowDecor.row_warn; ModList.jsx RowLabel's .row-warn): a bold
"!" in --warn, the row's own font size (not the badge font), one .row gap
after the name - or after the .dds badge when the row has both (every
.dds leftover does: no packageId is a warning) - also flex: none, so the
name is elided to leave room for both (the same _layout_badge, via
trailing_after); plain text on the name's baseline, not a bordered badge.
Its title (the warnings, one per line) is folded into the row tooltip. The
drag pill shows it the same way.
"""

import math
import time
from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QListView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from volt_py import theme
from volt_py.applog import log
from volt_py.mod_decorations import NO_DECOR, RowDecor, name_is_red, name_suffix


class ModListModel(QAbstractListModel):
    """A pane's mod ids, in order. rowCount/data for display (the row text is
    display_name(id); with `color`, the row's .row-color swatch is color(id)
    as the decoration - a QColor Qt paints itself, a square before the name;
    with `tooltip`, the row's tooltip is tooltip(id)); every change goes
    through the begin/end* calls, so the view and its selection follow it.
    With `decor`, decor_at(row) is decor(id) (the row's badge / outdated /
    dependency flags, a RowDecor), read by the delegate at paint time."""

    def __init__(
        self,
        display_name: Callable[[str], str],
        parent=None,
        color: Callable[[str], str | None] | None = None,
        decor: Callable[[str], RowDecor] | None = None,
        tooltip: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._display_name = display_name
        self._color = color
        self._decor = decor
        self._tooltip = tooltip
        self._ids: list[str] = []

    # ---- QAbstractListModel ----
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._ids)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._ids):
            return None
        mod_id = self._ids[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_name(mod_id)
        if self._color is not None and role == Qt.ItemDataRole.DecorationRole:
            color = self._color(mod_id)
            return QColor(color) if color else None
        if self._tooltip is not None and role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(mod_id)
        return None

    def decor_at(self, row: int) -> RowDecor:
        """`row`'s decorations (decor(id)); NO_DECOR without `decor` or out of range."""
        if self._decor is None or not 0 <= row < len(self._ids):
            return NO_DECOR
        return self._decor(self._ids[row])

    def refresh_colors(self) -> None:
        """The mod colors changed: every row's swatch is re-read."""
        if self._ids:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._ids) - 1, 0))

    def refresh_decorations(self) -> None:
        """The decorations changed (e.g. the selection's dependency
        highlighting): every row is re-read and repainted."""
        self.refresh_colors()

    # ---- reads ----
    def ids(self) -> list[str]:
        """The pane's ids in order (a copy)."""
        return list(self._ids)

    def id_at(self, row: int) -> str | None:
        return self._ids[row] if 0 <= row < len(self._ids) else None

    # ---- changes ----
    def set_ids(self, ids) -> None:
        """Replaces the whole list (repopulating a pane)."""
        self.beginResetModel()
        self._ids = list(ids)
        self.endResetModel()

    def insert_id(self, row: int, mod_id: str) -> None:
        """Inserts `mod_id` at `row` (clamped to 0..rowCount)."""
        row = min(max(row, 0), len(self._ids))
        self.beginInsertRows(QModelIndex(), row, row)
        self._ids.insert(row, mod_id)
        self.endInsertRows()

    def remove_row(self, row: int) -> str | None:
        """Removes and returns the id at `row`; None if out of range."""
        if not 0 <= row < len(self._ids):
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        mod_id = self._ids.pop(row)
        self.endRemoveRows()
        return mod_id

    def move_row(self, src: int, dst: int) -> bool:
        """Moves the id at `src` so it ends up at `dst` (ModList.jsx onDragEnd's
        arrayMove(ids, src, dst)). The only change a drag-reorder ever makes:
        ModListView calls it once, at the drop. False (nothing changed) if
        either row is out of range or they're equal.

        beginMoveRows takes the destination as the row to insert *before*, in
        pre-move numbering; moving down, that's one past `dst`."""
        n = len(self._ids)
        if src == dst or not (0 <= src < n and 0 <= dst < n):
            return False
        if not self.beginMoveRows(QModelIndex(), src, src, QModelIndex(), dst + 1 if dst > src else dst):
            return False
        self._ids.insert(dst, self._ids.pop(src))
        self.endMoveRows()
        return True


# ---- search (plain Python, no Qt) ----

def mod_matches(mods: dict, mod_id: str, q: str) -> bool:
    """lists.js modMatches, ported as is: `q` (already trimmed and
    lowercased) is in the mod's lowercased name, in its id, or in one of its
    lowercased authors. The id is compared as it is, not lowercased - like
    the JS's m.id; it is the scan's lowercased packageId key (mods.make_mod),
    so an id match is effectively case-insensitive too, but no lowercasing
    happens here. An id with no scanned mod (a not-found row: a pending
    Workshop id or a plain missing id in Active) falls back to the id itself,
    also as is - so a search finds it by its id (or the "workshop:" prefix),
    never by its Workshop title, exactly as the JS."""
    m = mods.get(mod_id)
    if m is None:
        return q in mod_id
    return q in m["name"].lower() or q in m["id"] or any(q in a.lower() for a in m["authors"])


# PaneSearch.mark values (.row.dimmed / .row.match).
MARK_DIM = "dimmed"
MARK_MATCH = "match"


class PaneSearch:
    """One pane's search (ModList.jsx query/dim), plain Python, no Qt:
    per pane, never persisted.

      query         the search box text, as typed
      color_filter  '#rrggbb' or None: only mods of that color (the context
                    menu's Filter by > This mod color)
      dim           the eye toggle: False (default) hides non-matches, True
                    dims them and marks the matches instead

    `match(id, q)` decides a text match (mod_matches, over the screen's
    mods), `color(id)` gives a mod's color. refresh(ids) recomputes the
    matching ids of the pane's list; everything else reads the last refresh,
    so call it after any change to the query, color filter, list, mods or
    mod colors:
      filtered  a query or a color filter is active
      hiding    filtered and the eye is closed: non-matches are hidden, and
                drag-reorder is off (ModList.jsx dragEnabled)
      matches   the ids matching both (None while not filtered)"""

    def __init__(self, match: Callable[[str, str], bool], color: Callable[[str], str | None] | None = None) -> None:
        self._match = match
        self._color = color
        self.query = ""
        self.color_filter: str | None = None
        self.dim = False
        self.matches: set[str] | None = None
        self.total = 0  # ids in the pane at the last refresh

    def refresh(self, ids) -> None:
        # ModList.jsx: (!q || modMatches(...)) && (!colorFilter || modColors[id] === colorFilter)
        ids = list(ids)
        q = self.query.strip().lower()
        cf = self.color_filter if self._color is not None else None
        self.total = len(ids)
        self.matches = (
            {i for i in ids if (not q or self._match(i, q)) and (not cf or self._color(i) == cf)}
            if q or cf else None
        )

    @property
    def filtered(self) -> bool:
        return self.matches is not None

    @property
    def hiding(self) -> bool:
        return self.matches is not None and not self.dim

    @property
    def no_matches(self) -> bool:
        """Hiding left no row visible (ModList.jsx: rows.length === 0 while
        hiding -> "No matches")."""
        return self.hiding and not self.matches

    def hidden(self, mod_id: str) -> bool:
        """The row is hidden (hiding mode, not a match)."""
        return self.hiding and mod_id not in self.matches

    def mark(self, mod_id: str) -> str | None:
        """Dim mode's row mark: MARK_MATCH / MARK_DIM; None when not dimming."""
        if self.matches is None or not self.dim:
            return None
        return MARK_MATCH if mod_id in self.matches else MARK_DIM

    def count_text(self) -> str:
        """The pane title's count: "matches/total" while filtered (hiding or
        dimming), else "total"."""
        return f"{len(self.matches)}/{self.total}" if self.matches is not None else str(self.total)


class DragPreview:
    """A drag-reorder in progress: the dragged row (`start_row`) and the row it
    would land on if dropped now (`target_row`), in a list of `row_count` rows.
    Plain ints, no Qt, never touches a model - the drop applies it once, as
    move_row(start_row, target_row).

    The previewed order is arrayMove(rows, start_row, target_row): the dragged
    row sits at the target and every row between the two shifts one slot
    toward the start to close the gap. The two mappings below describe the
    same order from either side:
      source_row(slot)  which row's content shows in visual slot `slot`
                        (what the delegate paints, slot by slot)
      offset(row)       how many slots `row`'s content is displaced by
                        (row + offset(row) is its slot; what SlideAnimation
                        interpolates)"""

    def __init__(self, row_count: int, start_row: int) -> None:
        if not 0 <= start_row < row_count:
            raise ValueError(f"start row {start_row} outside 0..{row_count - 1}")
        self.row_count = row_count
        self.start_row = start_row
        self.target_row = start_row

    def set_target(self, row: int) -> bool:
        """Moves the drop target to `row` (clamped to the list). True if it changed."""
        row = min(max(row, 0), self.row_count - 1)
        if row == self.target_row:
            return False
        self.target_row = row
        return True

    def source_row(self, slot: int) -> int:
        s, t = self.start_row, self.target_row
        if slot == t:
            return s
        if s < t and s <= slot < t:  # dragged down: the rows below it move up
            return slot + 1
        if t < s and t < slot <= s:  # dragged up: the rows above it move down
            return slot - 1
        return slot

    def offset(self, row: int) -> int:
        return preview_offset(self.start_row, self.target_row, row)


def preview_offset(start: int, target: int, row: int) -> int:
    """DragPreview.offset for a given start/target: the slots `row`'s content
    is displaced by in arrayMove(rows, start, target)."""
    if row == start:
        return target - start
    if start < row <= target:
        return -1
    if target <= row < start:
        return 1
    return 0


# ---- preview animation (plain Python, no Qt) ----

# How long a row's slide to its new slot takes (however many slots): the
# Electron app's, dnd-kit's default sortable transition (useSortable, 200ms).
# Its CSS curve ("ease") starts slowly; this one is an ease-out cubic
# (SCOPE.md §2), which covers 97% of the way in its first ~140ms.
# 0 = no animation (the preview snaps, as before slice 3).
SLIDE_MS = 200.0
# Frame spacing while a slide runs (both the frame timer and the drag moves'
# own frames are throttled to it): up to 100 frames a second.
SLIDE_FRAME_MS = 10


class Slide:
    """One leg of a row's slide: its displayed offset (in slots) goes from
    `start` at time `t0` to `end` at `t0 + duration` (ms) along an ease-out
    cubic, 1 - (1 - u)^3 - fastest at the start (3x the leg's average speed),
    slowing smoothly to a stop, never past either end. Plain numbers, no Qt."""

    __slots__ = ("start", "end", "t0", "duration")

    def __init__(self, start: float, end: float, t0: float, duration: float) -> None:
        self.start, self.end, self.t0, self.duration = start, end, t0, duration

    def done(self, now: float) -> bool:
        return now >= self.t0 + self.duration

    def value(self, now: float) -> float:
        if self.done(now):
            return self.end
        u = max(0.0, (now - self.t0) / self.duration)
        return self.start + (self.end - self.start) * (1.0 - (1.0 - u) ** 3)

    def velocity(self, now: float) -> float:
        """d value / d now, in slots per ms (0 once done)."""
        if self.done(now):
            return 0.0
        u = max(0.0, (now - self.t0) / self.duration)
        return (self.end - self.start) * 3.0 * (1.0 - u) ** 2 / self.duration


class SlideAnimation:
    """Animates a DragPreview: each row's content slides from where it is
    shown toward the slot the preview puts it in (DragPreview.offset), instead
    of snapping there. Plain Python, no Qt: times are ms, passed in by the
    caller; it reads the preview and never touches a model.

    Every change of target goes through set_target(row, now). Each row whose
    offset that changes gets a new leg (a Slide) from its displayed offset at
    `now` - so it never jumps, whether it was at rest or mid-slide - to its
    new offset:
      - duration: `duration`, scaled down for a leg shorter than one slot
        (duration * distance), so a row reversing a little way back doesn't
        crawl (CSS transitions' reversing shortening, generalised);
      - if the row was already moving toward the new end faster than the new
        leg would start (3 * distance / duration), the leg is shortened until
        its start speed equals the current speed. So a retarget never slows a
        row down along its direction of travel (no hitch from restarting an
        ease from rest): a row chasing a moving target keeps its speed or
        speeds up, a row reversing starts back at a fresh leg's speed.
    Rows whose offset didn't change keep their leg. Each leg ends within
    `duration` of the retarget that started it, exactly on the preview's
    offset, and never overshoots, so a shown position always lies between
    slots 0 and row_count - 1. duration 0: no legs at all, offsets are the
    preview's (no animation)."""

    def __init__(self, preview: DragPreview, duration: float) -> None:
        self.preview = preview
        self.duration = max(0.0, float(duration))
        self._slides: dict[int, Slide] = {}
        self._version = 0  # bumped on every change to _slides (cache key)
        self._bucket_key = None
        self._bucket: dict[int, list[tuple[int, float]]] = {}

    def slide(self, row: int) -> Slide | None:
        return self._slides.get(row)

    def offset(self, row: int, now: float) -> float:
        """`row`'s displayed offset (slots) at `now`."""
        slide = self._slides.get(row)
        return slide.value(now) if slide is not None else float(self.preview.offset(row))

    def active(self, now: float) -> bool:
        """Any row still sliding at `now`."""
        return any(not s.done(now) for s in self._slides.values())

    def set_target(self, row: int, now: float) -> bool:
        """DragPreview.set_target, animated from `now`. True if the target changed."""
        preview = self.preview
        old = preview.target_row
        if not preview.set_target(row):
            return False
        new, start = preview.target_row, preview.start_row
        # The rows whose offset can change: the dragged row and those between
        # the old and the new target.
        rows = set(range(min(old, new), max(old, new) + 1))
        rows.add(start)
        for r in sorted(rows):
            end = float(preview.offset(r))
            slide = self._slides.get(r)
            if slide is not None:
                if slide.end == end:
                    continue  # still heading to the same slot: keep its leg
                current, speed = slide.value(now), slide.velocity(now)
            else:
                current, speed = float(preview_offset(start, old, r)), 0.0
                if current == end:
                    continue
            self._retarget(r, current, speed, end, now)
        self._version += 1
        return True

    def _retarget(self, row: int, current: float, speed: float, end: float, now: float) -> None:
        distance = end - current
        if self.duration <= 0 or abs(distance) < 1e-9:
            self._slides.pop(row, None)  # shown at the preview's offset from now on
            return
        duration = self.duration * min(1.0, abs(distance))
        if speed * distance > 0:  # already moving that way: don't slow it down
            duration = min(duration, 3.0 * abs(distance) / abs(speed))
        self._slides[row] = Slide(current, end, now, duration)

    def prune(self, now: float) -> None:
        """Forgets the legs finished by `now` (their rows show the preview's offset)."""
        kept = {r: s for r, s in self._slides.items() if not s.done(now)}
        if len(kept) != len(self._slides):
            self._slides = kept
            self._version += 1

    def contents(self, slot: int, now: float) -> list[tuple[int, float]]:
        """What shows (even partly) in visual slot `slot` at `now`: (row,
        position) for every row whose displayed position - row + offset, in
        slots - is less than one slot away from it, dragged row last. A row
        at rest is exactly in its slot (position == slot); a sliding row can
        straddle two slots and is listed for both."""
        preview = self.preview
        out = []
        occupant = preview.source_row(slot)
        if occupant not in self._slides:
            out.append((occupant, float(slot)))
        out.extend(self._sliding_by_slot(now).get(slot, ()))
        out.sort(key=lambda c: (c[0] == preview.start_row, c[0]))
        return out

    def _sliding_by_slot(self, now: float) -> dict[int, list[tuple[int, float]]]:
        key = (now, self._version)
        if key != self._bucket_key:
            bucket: dict[int, list[tuple[int, float]]] = {}
            for r, s in self._slides.items():
                pos = r + s.value(now)
                below = math.floor(pos)
                bucket.setdefault(below, []).append((r, pos))
                if pos != below:
                    bucket.setdefault(below + 1, []).append((r, pos))
            self._bucket_key, self._bucket = key, bucket
        return self._bucket


def _now_ms() -> float:
    """The animation clock (ms): perf_counter, monotonic and high-resolution
    on every platform."""
    return time.perf_counter() * 1000.0


# .row.dragging { opacity: 0.35 }: the dragged row's own card, shown faded in
# the slot it would drop into (dnd-kit moves the dragged item's placeholder
# there too); the floating pill (DragOverlay) is what follows the cursor.
DRAGGED_ROW_OPACITY = 0.35
# .row.dimmed { opacity: 0.35 }: a non-match in search dim mode. The same
# opacity property as .dragging, so a dimmed dragged row is 0.35, not less.
DIMMED_ROW_OPACITY = 0.35
# .row.match { box-shadow: inset 3px 0 0 var(--accent) }: a match in dim mode.
# .row.dependency / .row.dependent's inset bars are the same width.
MATCH_BAR_WIDTH = 3
# .row-badge (styles.css; box-sizing: border-box): 10px bold text in a 13px
# line, 3px side padding, 1px border, 2px radius, min-width 14px.
BADGE_TEXT = "L"  # the Official badge's width reference: the old "L" + padding; the glyph is a drawn check
DDS_BADGE_TEXT = ".dds"  # .row-badge.dds-leftover: same box, --muted border + text
ROW_WARN_TEXT = "!"  # .row-warn: plain text, bold, --warn, the row's font size
BADGE_FONT_PX = 10
BADGE_HEIGHT = 15  # line-height 13 + the 1px border top and bottom
BADGE_MIN_WIDTH = 14
BADGE_RADIUS = 2
BADGE_SIDES = 8  # padding 3 + border 1, both sides
BADGE_CHECK_PX = 10  # the Official badge's drawn check (logical px; the box's inside is 12 x 13)
ROW_GAP = 6  # .row { gap: 6px }: swatch | badge | name
SWATCH_SIZE = 10  # .row-color (ModListView's icon size)
ROW_PADDING = 8  # .row { padding: 0 8px } (the ::item rule's side padding)
# .row-issues / .row-issue (ModList.jsx RowIssues): the Active pane's per-row
# issue icons, left to right - (severity, icons.py name, color) - drawn like
# the Valheim rows' marks (bepinex_mod_list.py), ISSUE_ICON_PX square, in
# --warn / --danger, 4px apart, the cross always rightmost.
ISSUE_ICONS = (
    ("warning", "warn", theme.WARN),
    ("error", "x", theme.DANGER),
)
ISSUE_ICON_PX = 14  # = bepinex_mod_list.MARK_PX
ISSUE_GAP = 4  # .row-issues { gap: 4px }
# .row.downloading { opacity: 0.6 }: a not-found Workshop row with a Subscribe
# under way. In styles.css it sits after .row.dragging and before
# .row.dimmed, so on one row dimmed (0.35) beats it and it beats dragging.
DOWNLOADING_ROW_OPACITY = 0.6
# .row-name.pending em / .row-name.missing em: the muted suffix, 11px.
SUFFIX_FONT_PX = 11
# .row-subscribe on button.accent-outline: 11px text on a 16px line, 8px side
# padding, a 1px --accent border (--muted on hover: button:hover), --radius
# corners (a pill at this height), --panel-2 fill, --accent text; pushed to
# the row's right end (margin-left: auto).
SUBSCRIBE_TEXT = "Subscribe"
SUBSCRIBE_FONT_PX = 11
SUBSCRIBE_HEIGHT = 18  # line-height 16 + the 1px border top and bottom
SUBSCRIBE_SIDES = 18  # padding 8 + border 1, both sides
DISABLED_BUTTON_OPACITY = 0.5  # button:disabled { opacity: 0.5 }
# The Subscribe button's kind in ModListView.control_at / _issue_press (the
# issue icons' kinds are their severities).
SUBSCRIBE = "subscribe"
# .row.pending { outline: 1px dashed }: Chromium dashes a 1px line 3px on, 3px off.
PENDING_DASH = (3.0, 3.0)
# Hover/focus belong to whatever row is really under the cursor, not to the
# shifted content painted there; selection is re-derived from the source row.
_PREVIEW_CLEARED_STATES = (
    QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_HasFocus
)


class ModRowDelegate(QStyledItemDelegate):
    """Paints a mod row. Normal rows are the base QStyledItemDelegate paint:
    it draws through the view's style, i.e. the style sheet's ::item rules
    (card background, radius, margins, padding, hover, selected), and its
    sizeHint includes the ::item margins/padding.

    During a drag (view.drag_preview set) each visual slot paints the content
    the (animated) preview shows there - ModListView.slot_contents(slot) -
    through the same base paint: the rows between the drag's start and target
    show their neighbor's card (i.e. slide one slot to close the gap), the
    target slot shows the dragged row's card at DRAGGED_ROW_OPACITY. At rest,
    a content is painted at the slot's own rect. Mid-slide, it is painted at
    its animated position (the slot rect moved to ModListView.slide_top),
    clipped to the slot: a card straddling two slots is painted as two
    clipped halves, one by each slot's paint, which meet exactly.

    Why paint per slot (not each row at an offset rect): QListView only asks
    the delegate for rows whose own rect is in the paint region, so a row
    whose real position is out of view - scrolled away, or just past the edge
    while its content slides in - would never be painted. Every visible pixel
    a content can reach lies in some visible slot (displayed positions stay
    between slots 0 and n - 1), and Qt asks for every visible slot, so this
    paints everything with Qt's own paint loop and item options; the view
    needs no paintEvent of its own.

    Search dim mode (ModListView.search_mark): a non-match's card is painted
    at DIMMED_ROW_OPACITY, a match's gets the accent bar (paint_match_bar).
    Mid-drag the mark follows the content (the source row), like the CSS
    classes on a dnd-kit row that is only moved by a transform. Hiding mode
    needs nothing here: hidden rows are never painted.

    Row decorations (ModListModel.decor_at, a RowDecor) follow the content
    the same way. The badge and the name color go into the item's style
    option (initStyleOption, which Qt's base paint and sizeHint call), so the
    base paint draws them in its own layout. A dependency / dependent row's
    card is replaced by the tint (paint_row_tint, painted before the base
    paint, which draws a transparent card for it - see initStyleOption) and
    gets its inset bars on top (paint_row_bars); a dependency's left bar wins
    over a search match's accent bar, a dependent's right bar goes with it
    (styles.css .row.match.dependency / .row.match.dependent).

    Validation marks, same way: a row's issue icons (ModListView.issue_icons)
    are painted after the base paint and the bars, a conflicting row's --warn
    outline last of all - all under the card's clip and opacity (a dimmed or
    dragged row fades them too, as CSS opacity does a row's children). A
    row with none of the three takes exactly the old paths.

    Pending / downloading rows (module docstring), same way: their suffix
    after the base paint (laid out by initStyleOption while _suffix is set),
    then the issue icons (if any, left of the button), the Subscribe button,
    and the pending dashed outline where a conflict outline would go.

    A scanned mod's trailing .dds badge and "!" warning mark, same way: laid
    out by initStyleOption while _badge_after / _warn_after are set, painted
    after the base paint (the badge, then the mark), under the card's clip
    and opacity."""

    def __init__(self, view: "ModListView") -> None:
        super().__init__(view)
        self._view = view
        self._badge_icons: dict = {}  # (swatch color, dpr, font) -> (QIcon, QSize)
        # Set only around the base paint of a row with issue icons (or a
        # Subscribe button): the x (viewport px) its name must end before
        # (initStyleOption elides it).
        self._text_right: int | None = None
        # Set only around the base paint of a row with a name suffix
        # (mod_decorations.name_suffix); initStyleOption then leaves where
        # to paint it in _suffix_at: (x, baseline y, text), or None.
        self._suffix: str | None = None
        self._suffix_at: tuple[int, int, str] | None = None
        # Likewise for a .dds-leftover row: _badge_after set around its base
        # paint, initStyleOption leaves the trailing badge's rect in _badge_at.
        self._badge_after = False
        self._badge_at: QRectF | None = None
        # And for a row with mod warnings: _warn_after set around its base
        # paint, initStyleOption leaves the "!" mark's (x, baseline y) in _warn_at.
        self._warn_after = False
        self._warn_at: tuple[int, int] | None = None

    def initStyleOption(self, option, index) -> None:
        """The base paint's (and sizeHint's) item option, plus the row's
        decorations. Real Qt calls this; the check harnesses' fake base paint
        doesn't.
          - name color: --danger if outdated or conflicting (RowLabel's
            outdated || conflict), else --text - in the palette's
            Text (unselected) and HighlightedText (selected) roles, so the
            red survives selection (.row-name.outdated). theme.py's
            ::item:selected sets no `color` for this reason (a style-sheet
            color would override HighlightedText); --text for a selected
            row comes from here instead.
          - dependency / dependent: the Alternate feature. The mod lists
            never use alternating row colors, so it only selects theme.py's
            ::item:alternate rule - a transparent card (after :hover /
            :selected, so it wins over both, as .row.dependency does over
            .row:hover) - and the tint _paint_card painted first shows
            through, under the base paint's name and swatch.
          - official: the decoration becomes swatch (if any) + gap + badge,
            one pixmap (_badge_icon), so the base paint puts the name after
            it with the same spacing it uses after a lone swatch.
          - issue icons (only while _paint_card paints such a row, which
            sets _text_right): the name is elided (…) to end before them,
            as .row-name's text-overflow: ellipsis does next to .row-issues.
          - a name suffix (only while _paint_card sets _suffix): the name
            and the suffix laid out together (_layout_suffix).
          - a trailing .dds badge and / or "!" warning mark (only while
            _paint_card sets _badge_after / _warn_after): the name elided
            to leave room for them (_layout_badge).
          - name color: mod_decorations.name_is_red (a pending row's name
            is never red; a downloading one's always is)."""
        super().initStyleOption(option, index)
        from PySide6.QtGui import QPalette

        decor = self._view.mod_model.decor_at(index.row()) if index.isValid() else NO_DECOR
        red = name_is_red(decor)
        # Copied, changed, assigned back: a struct member read may be a copy.
        palette = QPalette(option.palette)
        name_color = QColor(theme.DANGER if red else theme.TEXT)
        palette.setColor(QPalette.ColorRole.HighlightedText, name_color)
        if red:
            palette.setColor(QPalette.ColorRole.Text, name_color)
        option.palette = palette
        if decor.dependency or decor.dependent:
            option.features = option.features | QStyleOptionViewItem.ViewItemFeature.Alternate
        if decor.official:
            swatch = index.data(Qt.ItemDataRole.DecorationRole)
            icon, size = self._badge_icon(swatch if isinstance(swatch, QColor) else None)
            option.icon = icon
            option.decorationSize = size
            option.features = option.features | QStyleOptionViewItem.ViewItemFeature.HasDecoration
        if self._suffix is not None and option.text:
            self._layout_suffix(option, self._suffix, self._text_right)
        elif self._badge_after or self._warn_after:
            self._layout_badge(option, self._text_right)
        elif self._text_right is not None and option.text:
            self._elide_before(option, self._text_right)

    def _layout_suffix(self, option, suffix: str, right: int | None) -> None:
        """A not-found row's name plus its muted suffix (RowLabel's <em>, which
        sits inside .row-name and so inside its ellipsis): the name, a space
        (in the name's font) and the suffix in suffix_font, ending before
        viewport x `right` (None: the style's own text rect end). What
        doesn't fit is cut from the end - the suffix elided first
        (suffix_room), then the name elided with no suffix at all. Leaves
        the suffix's place in _suffix_at for _paint_card: on the name's
        baseline (Qt draws the item text vertically centered in the text
        rect), as inline text shares its line's baseline."""
        from PySide6.QtGui import QFontMetrics

        view = self._view
        style = view.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, view)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, view) + 1
        left = text_rect.left() + margin
        if right is None:
            right = text_rect.right() + 1 - margin
        metrics, suffix_metrics = option.fontMetrics, QFontMetrics(suffix_font(view))
        name_w, space_w = metrics.horizontalAdvance(option.text), metrics.horizontalAdvance(" ")
        suffix_w = suffix_metrics.horizontalAdvance(suffix)
        room = suffix_room(name_w, space_w, suffix_w, right - left)
        if room is None:
            option.text = metrics.elidedText(option.text, Qt.TextElideMode.ElideRight, max(0, right - left))
            return
        text = suffix if room >= suffix_w else suffix_metrics.elidedText(suffix, Qt.TextElideMode.ElideRight, room)
        if text:
            top = text_rect.top() + (text_rect.height() - metrics.height()) // 2
            self._suffix_at = (left + name_w + space_w, top + metrics.ascent(), text)

    def _layout_badge(self, option, right: int | None) -> None:
        """A scanned mod's name and what trails it (RowLabel's
        .row-badge.dds-leftover (if _badge_after), then .row-warn (if
        _warn_after), after .row-name; both flex: none, the name's box
        shrinks with an ellipsis): the name elided to end before them, and
        them before viewport x `right` (None: the style's own text rect
        end), each ROW_GAP after the previous box (trailing_after). The
        badge vertically centered on the text rect, its rect left in
        _badge_at; the "!" on the name's baseline (inline text, as
        _layout_suffix's), its (x, baseline) left in _warn_at - both for
        _paint_card."""
        view = self._view
        style = view.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, view)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, view) + 1
        left = text_rect.left() + margin
        if right is None:
            right = text_rect.right() + 1 - margin
        widths = []
        if self._badge_after:
            badge_w = badge_width(badge_font(view), DDS_BADGE_TEXT)
            widths.append(badge_w)
        if self._warn_after:
            widths.append(issue_glyph_width(view, ROW_WARN_TEXT))
        metrics = option.fontMetrics
        name_w = metrics.horizontalAdvance(option.text)
        room, xs = trailing_after(name_w, widths, right - left)
        if name_w > room:
            option.text = metrics.elidedText(option.text, Qt.TextElideMode.ElideRight, room)
        if self._badge_after:
            # whole px: a crisp border
            top = math.floor(text_rect.top() + (text_rect.height() - BADGE_HEIGHT) / 2 + 0.5)
            self._badge_at = QRectF(left + xs[0], top, badge_w, BADGE_HEIGHT)
        if self._warn_after:
            top = text_rect.top() + (text_rect.height() - metrics.height()) // 2
            self._warn_at = (left + xs[-1], top + metrics.ascent())

    def _elide_before(self, option, right: int) -> None:
        """Elides option.text so the name, where the style draws it, ends
        before viewport x `right`: the style's own text rect for this option
        (::item padding, swatch / badge decoration) minus the text margin
        Qt's item painting keeps inside it (PM_FocusFrameHMargin + 1)."""
        view = self._view
        style = view.style()
        text_rect = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, view)
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, option, view) + 1
        available = right - text_rect.left() - margin
        metrics = option.fontMetrics
        if metrics.horizontalAdvance(option.text) > available:
            option.text = metrics.elidedText(option.text, Qt.TextElideMode.ElideRight, max(0, available))

    def helpEvent(self, event, view, option, index) -> bool:
        """Tooltips: over an issue icon, that icon's own (ModListView
        .issue_tooltip - the .row-issue span's title, which wins over the
        row's); over a Subscribe button, the button's (subscribe_tip);
        elsewhere the row's ToolTipRole, as before."""
        if event is not None and event.type() == QEvent.Type.ToolTip:
            tip = self._view.issue_tooltip(event.pos())
            if tip is None:
                tip = self._view.subscribe_tip(event.pos())
            if tip is not None:
                from PySide6.QtWidgets import QToolTip

                text, rect = tip
                # rect: the tooltip hides once the cursor leaves the icon, so
                # the row's own tooltip can show next.
                QToolTip.showText(event.globalPos(), text, self._view.viewport(), rect)
                return True
        return super().helpEvent(event, view, option, index)

    def _badge_icon(self, swatch):
        """(QIcon, logical QSize) of an official row's decoration: the
        .row-color swatch `swatch` (a QColor, or None: no swatch) and the
        .row-badge, ROW_GAP apart, vertically centered on the badge. Drawn at
        the view's device pixel ratio (crisp text), cached per swatch color.
        The same pixmap serves the Selected mode too: the badge keeps its
        opaque OFFICIAL_FILL chip on a selected row (no selection wash)."""
        from PySide6.QtGui import QIcon

        view = self._view
        dpr = view.devicePixelRatioF()
        font = badge_font(view)
        key = (swatch.name() if swatch is not None else None, dpr, font.key())
        cached = self._badge_icons.get(key)
        if cached is not None:
            return cached
        badge_w = badge_width(font)
        x = SWATCH_SIZE + ROW_GAP if swatch is not None else 0
        w, h = x + badge_w, BADGE_HEIGHT
        pixmap = QPixmap(max(1, round(w * dpr)), max(1, round(h * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        if swatch is not None:
            # (15 - 10 + 1) // 2: rounded down it would sit 1px high of a
            # lone swatch (centered in the row) on an even-height row.
            painter.fillRect(QRectF(0, (h - SWATCH_SIZE + 1) // 2, SWATCH_SIZE, SWATCH_SIZE), swatch)
        paint_row_badge(painter, QRectF(x, 0, badge_w, h), font)
        painter.end()
        icon = QIcon()
        icon.addPixmap(pixmap, QIcon.Mode.Normal)
        icon.addPixmap(pixmap, QIcon.Mode.Selected)
        cached = self._badge_icons[key] = (icon, QSize(w, h))
        return cached

    def paint(self, painter, option, index) -> None:
        view = self._view
        preview = view.drag_preview
        contents = view.slot_contents(index.row()) if preview is not None and index.isValid() else None
        if contents is None:
            mark = view.search_mark(index.row()) if index.isValid() else None
            self._paint_card(painter, option, index, None, False, mark)
            return
        slot, slot_rect = index.row(), option.rect
        for row, pos in contents:
            source_index = view.mod_model.index(row, 0)
            if not source_index.isValid():  # the model changed under the drag
                if pos == slot:  # the slot's own row, as with no drag
                    self._paint_card(painter, option, index, None, False, view.search_mark(slot))
                continue
            faded = row == preview.start_row
            mark = view.search_mark(row)
            if pos == slot:  # at rest in this slot
                self._paint_content(painter, option, source_index, slot_rect, None, faded, mark)
                continue
            top = view.slide_top(pos)
            if top is None:
                continue
            rect = slot_rect.translated(0, top - slot_rect.top())
            if rect.intersects(slot_rect):
                self._paint_content(painter, option, source_index, rect, slot_rect, faded, mark)

    def _paint_content(self, painter, option, source_index, rect, clip, faded: bool, mark: str | None) -> None:
        """`source_index`'s card at `rect` (clipped to `clip`, if any), through
        the base paint. Hover/focus cleared, selection re-derived from the
        source row; the dragged row's card faded; its search mark, if any."""
        opt = QStyleOptionViewItem(option)
        opt.rect = rect
        opt.state = opt.state & ~_PREVIEW_CLEARED_STATES
        if self._view.selectionModel().isSelected(source_index):
            opt.state = opt.state | QStyle.StateFlag.State_Selected
        self._paint_card(painter, opt, source_index, clip, faded, mark)

    def _paint_card(self, painter, opt, index, clip, faded: bool, mark: str | None) -> None:
        """The base paint of `index` with `opt`: clipped to `clip` (if any),
        faded if it's the dragged row or a search-dimmed one (one opacity,
        not compounded - both are .row's opacity), then a search match's
        accent bar on top. A dependency / dependent row (decor_at) gets its
        tint under the base paint and its inset bars on top, all under the
        same clip and opacity; then its issue icons (the name elided before
        them) and last a conflict's outline. A pending / downloading row
        adds its name suffix, its Subscribe button and (pending, no
        conflict) the dashed outline in the same order (class docstring);
        a downloading row is faded. A .dds-leftover row's badge follows
        its name, after the base paint, and a row with mod warnings its "!"
        (after the badge, if both). Plain rows are just the base paint."""
        view = self._view
        decor = view.mod_model.decor_at(index.row()) if index.isValid() else NO_DECOR
        # the card-shaped paints' item rect, shifted by the rail's wider left margin (no-op without the rail):
        # _card_rectf insets by theme.ROW_MARGINS
        bars_rect = opt.rect.adjusted(theme.row_margins(view)[0] - theme.ROW_MARGINS[0], 0, 0, 0)
        # One .row opacity, the later styles.css rule winning (DOWNLOADING_ROW_OPACITY).
        opacity = (
            DIMMED_ROW_OPACITY if mark == MARK_DIM
            else DOWNLOADING_ROW_OPACITY if decor.downloading
            else DRAGGED_ROW_OPACITY if faded
            else None
        )
        bar = mark == MARK_MATCH
        tinted = decor.dependency or decor.dependent
        # Icons only in a view that takes their clicks (the Active pane); the
        # Subscribe button likewise (subscribe_rect: None without on_subscribe).
        live = view._on_show_issue is not None
        icons = view.issue_icons(decor, opt.rect) if live and (decor.warning or decor.error) else []
        subscribe = view.subscribe_rect(decor, opt.rect)
        suffix = name_suffix(decor)
        if (clip is None and opacity is None and not bar and not tinted and not icons and not decor.conflict
                and suffix is None and subscribe is None and not decor.dds_leftover and not decor.row_warn):
            super().paint(painter, opt, index)
            return
        painter.save()
        if clip is not None:
            painter.setClipRect(clip, Qt.ClipOperation.IntersectClip)
        if opacity is not None:
            painter.setOpacity(opacity)
        if tinted:
            paint_row_tint(painter, bars_rect, decor.dependency, decor.dependent)
        controls_left = icons[0][3].left() if icons else subscribe.left() if subscribe is not None else None
        if controls_left is not None:
            self._text_right = controls_left - ROW_GAP  # .row gap between the name and .row-issues / the button
        self._suffix = suffix
        self._badge_after = decor.dds_leftover
        self._warn_after = decor.row_warn
        try:
            super().paint(painter, opt, index)
        finally:
            self._text_right = self._suffix = None
            self._badge_after = self._warn_after = False
            suffix_at, self._suffix_at = self._suffix_at, None
            badge_at, self._badge_at = self._badge_at, None
            warn_at, self._warn_at = self._warn_at, None
        if tinted:
            left = theme.DEP if decor.dependency else theme.ACCENT if bar else None
            paint_row_bars(painter, bars_rect, left, theme.RDEP if decor.dependent else None)
        elif bar:
            paint_match_bar(painter, bars_rect)
        if suffix_at is not None:
            paint_row_suffix(painter, suffix_at, view)
        if badge_at is not None:
            paint_row_badge(painter, badge_at, badge_font(view), DDS_BADGE_TEXT, theme.MUTED)
        if warn_at is not None:
            paint_row_warn(painter, warn_at, view)
        if icons:
            paint_issue_icons(painter, icons, view)
        if subscribe is not None:
            paint_subscribe_button(painter, subscribe, view, view.subscribe_hovered(index.row()),
                                   view.subscribe_is_enabled())
        if decor.conflict:
            paint_conflict_outline(painter, bars_rect)
        elif decor.pending:
            paint_pending_outline(painter, bars_rect)
        painter.restore()


def paint_match_bar(painter, rect) -> None:
    """.row.match's `box-shadow: inset 3px 0 0 var(--accent)` on the card in
    item rect `rect` (inset by theme.ROW_MARGINS, as the ::item rule's
    margin places the card). An inset shadow offset 3px right, no blur, is
    the card's rounded shape minus the same shape moved 3px right: a bar
    3px wide at every height, following the rounded left corners. Painted
    after the base paint - the name starts past .row's 8px padding, so the
    bar never covers it. The caller saves/restores the painter.

    (paint_row_bars; its QPainterPath is imported there, not at the top:
    tools/checks/volt_py_drag_reorder.py runs this module over a fake
    PySide6 without it - that check never paints a search mark.)"""
    paint_row_bars(painter, rect, theme.ACCENT, None)


def _card_rectf(rect) -> QRectF:
    """The row card inside item rect `rect`, as the ::item rule's margin
    places it (theme.ROW_MARGINS)."""
    left, top, right, bottom = theme.ROW_MARGINS
    return QRectF(rect.adjusted(left, top, -right, -bottom))


def paint_row_bars(painter, rect, left: str | None, right: str | None) -> None:
    """Inset bars MATCH_BAR_WIDTH wide on the card in item rect `rect`:
    `left` ('#rrggbb' or None) is `box-shadow: inset 3px 0 0 <left>`,
    `right` is `inset -3px 0 0 <right>` - each the card's rounded shape
    minus the same shape moved 3px inward, following the rounded corners
    (.row.match, .row.dependency, .row.dependent and their combinations).
    Painted after the base paint: the name sits past .row's 8px padding on
    either side, so a bar never covers it. The caller saves/restores the
    painter. QPainterPath imported here, as in paint_match_bar."""
    from PySide6.QtGui import QPainterPath

    card = _card_rectf(rect)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for color, dx in ((left, MATCH_BAR_WIDTH), (right, -MATCH_BAR_WIDTH)):
        if color is None:
            continue
        outer, inner = QPainterPath(), QPainterPath()
        outer.addRoundedRect(card, theme.RADIUS, theme.RADIUS)
        inner.addRoundedRect(card.translated(dx, 0), theme.RADIUS, theme.RADIUS)
        painter.fillPath(outer.subtracted(inner), QColor(color))


def paint_row_tint(painter, rect, dependency: bool, dependent: bool) -> None:
    """The card background of a .row.dependency (--dep-bg), .row.dependent
    (--rdep-bg) or both (linear-gradient(90deg, --dep-bg, --rdep-bg)) in item
    rect `rect`: the card's rounded shape filled with the translucent tint,
    over the list's --panel background - it replaces the --panel-2 card, it
    isn't a wash over it (the base paint then draws a transparent card:
    ModRowDelegate.initStyleOption). Painted before the base paint, so the
    name and swatch land on top. The caller saves/restores the painter.
    Qt imports here, as in paint_match_bar."""
    from PySide6.QtGui import QBrush, QLinearGradient, QPainterPath

    card = _card_rectf(rect)
    if dependency and dependent:
        gradient = QLinearGradient(card.left(), 0.0, card.right(), 0.0)
        gradient.setColorAt(0.0, css_color(theme.DEP_BG))
        gradient.setColorAt(1.0, css_color(theme.RDEP_BG))
        brush = QBrush(gradient)
    else:
        brush = QBrush(css_color(theme.DEP_BG if dependency else theme.RDEP_BG))
    path = QPainterPath()
    path.addRoundedRect(card, theme.RADIUS, theme.RADIUS)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillPath(path, brush)


def css_color(value: str) -> QColor:
    """A theme.py color token as a QColor: '#rrggbb', or 'rgba(r, g, b, a)'
    (the --dep-bg / --rdep-bg form, which QColor doesn't parse itself; alpha
    0..1 rounded to 0..255, as browsers do)."""
    value = value.strip()
    if value.startswith("rgba(") and value.endswith(")"):
        r, g, b, a = (part.strip() for part in value[5:-1].split(","))
        return QColor(int(r), int(g), int(b), round(float(a) * 255))
    return QColor(value)


def badge_font(widget):
    """.row-badge's font: the widget's family, BADGE_FONT_PX, bold."""
    from PySide6.QtGui import QFont

    font = QFont(widget.font())
    font.setPixelSize(BADGE_FONT_PX)
    font.setWeight(QFont.Weight.Bold)
    return font


def badge_width(font, text: str = BADGE_TEXT) -> int:
    """.row-badge's border-box width: its `text` + padding + border, at least
    BADGE_MIN_WIDTH (14px for "L")."""
    from PySide6.QtGui import QFontMetrics

    return max(BADGE_MIN_WIDTH, QFontMetrics(font).horizontalAdvance(text) + BADGE_SIDES)


def badge_after(name_w: int, badge_w: int, available: int) -> tuple[int, int]:
    """A name followed by a flex: none badge, ROW_GAP apart, in `available`
    px (widths in px): (the name's room - elide it when wider -, the badge's
    x offset from the name's left: just past the name's box, which shrinks
    to that room). Plain arithmetic, for ModRowDelegate._layout_badge and
    the drag pill."""
    room = max(0, available - ROW_GAP - badge_w)
    return room, min(name_w, room) + ROW_GAP


def trailing_after(name_w: int, widths: list[int], available: int) -> tuple[int, list[int]]:
    """badge_after for one or more flex: none elements after the name (the
    .dds badge, then the "!" warning mark), each ROW_GAP after the previous
    box: (the name's room, each element's x offset from the name's left).
    One width is exactly badge_after. For ModRowDelegate._layout_badge and
    the drag pill."""
    room, x = badge_after(name_w, sum(widths) + ROW_GAP * (len(widths) - 1), available)
    xs = []
    for w in widths:
        xs.append(x)
        x += w + ROW_GAP
    return room, xs


def paint_row_badge(painter, rect: QRectF, font, text: str | None = None, color: str = theme.OFFICIAL,
                    edge: str | None = None, fill: str | None = None) -> None:
    """.row-badge in `rect` (badge_width x BADGE_HEIGHT), BADGE_RADIUS corners.
    text None = the Official (Core/DLC) badge: an OFFICIAL_FILL chip, 1px
    OFFICIAL_EDGE border, a drawn check (icons.py "check") in `color`
    (OFFICIAL), centred. With `text` (the .dds leftover, the BepInEx status
    pills): a --panel-2 fill, a 1px `color` border and `text` in `color` -
    edge / fill override the border / fill colour only when given."""
    from PySide6.QtCore import QPointF

    official = text is None
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(edge or (theme.OFFICIAL_EDGE if official else color)), 1))
    painter.setBrush(QColor(fill or (theme.OFFICIAL_FILL if official else theme.PANEL_2)))
    # The 1px stroke centered on the half-pixel inset: its outer edge is the
    # rect, its outer corner radius BADGE_RADIUS.
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), BADGE_RADIUS - 0.5, BADGE_RADIUS - 0.5)
    if official:
        from volt_py import icons  # local: keeps the stdlib harnesses' import graph as today

        dpr = painter.device().devicePixelRatioF()
        side = BADGE_CHECK_PX
        # Whole device px: a crisp 1-device-px stroke.
        x = round((rect.center().x() - side / 2) * dpr) / dpr
        y = round((rect.center().y() - side / 2) * dpr) / dpr
        painter.drawPixmap(QPointF(x, y), icons.pixmap("check", color, side, dpr))
    else:
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.restore()


def issue_font(widget):
    """.row-issue's font: the widget's (the row's), bold (font-weight 700)."""
    from PySide6.QtGui import QFont

    font = QFont(widget.font())
    font.setWeight(QFont.Weight.Bold)
    return font


def issue_glyph_width(widget, glyph: str) -> int:
    """An issue icon's width: ISSUE_ICON_PX for a drawn issue icon (an
    ISSUE_ICONS name); for a text mark (ROW_WARN_TEXT) its advance in
    issue_font. (Module level so the check harnesses, which have no real
    fonts, can patch it.)"""
    if any(glyph == name for _severity, name, _color in ISSUE_ICONS):
        return ISSUE_ICON_PX
    from PySide6.QtGui import QFontMetrics

    return QFontMetrics(issue_font(widget)).horizontalAdvance(glyph)


def paint_issue_icons(painter, icons, widget) -> None:
    """The .row-issue icons: each (severity, icons.py name, color, rect) of
    ModListView.issue_icons, drawn ISSUE_ICON_PX square in its color,
    centered in its rect (the card's height), snapped to whole device px.
    The caller saves/restores the painter (clip, opacity)."""
    from PySide6.QtCore import QPointF

    from volt_py import icons as drawn  # local: keeps the stdlib harnesses' import graph as today

    dpr = painter.device().devicePixelRatioF()
    side = ISSUE_ICON_PX
    for _severity, name, color, rect in icons:
        box = QRectF(rect)
        x = round((box.center().x() - side / 2) * dpr) / dpr
        y = round((box.center().y() - side / 2) * dpr) / dpr
        painter.drawPixmap(QPointF(x, y), drawn.pixmap(name, color, side, dpr))


def paint_conflict_outline(painter, rect) -> None:
    """.row.conflict's `outline: 1px solid var(--warn); outline-offset: -1px`
    on the card in item rect `rect`: the card's outermost pixel ring, along
    its rounded corners (Chromium outlines follow border-radius). Painted
    last, over the dependency tint's bars (an outline is drawn above the
    element's box-shadow). The caller saves/restores the painter."""
    card = _card_rectf(rect)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(theme.WARN), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # The 1px stroke centered on the half-pixel inset: its outer edge is the card's.
    painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS - 0.5, theme.RADIUS - 0.5)


def paint_pending_outline(painter, rect) -> None:
    """.row.pending's `outline: 1px dashed var(--border); outline-offset:
    -1px` on the card in item rect `rect`: paint_conflict_outline's ring,
    dashed PENDING_DASH with flat caps (a square cap would lengthen every
    dash by the pen width). The caller saves/restores the painter."""
    card = _card_rectf(rect)
    pen = QPen(QColor(theme.BORDER), 1)
    pen.setDashPattern(list(PENDING_DASH))
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS - 0.5, theme.RADIUS - 0.5)


def suffix_font(widget):
    """The name suffix's font (.row-name em): the widget's, SUFFIX_FONT_PX."""
    from PySide6.QtGui import QFont

    font = QFont(widget.font())
    font.setPixelSize(SUFFIX_FONT_PX)
    return font


def suffix_room(name_w: int, space_w: int, suffix_w: int, available: int) -> int | None:
    """Laying out a name, a space and a suffix in `available` px (all widths
    in px): the suffix's room - suffix_w when everything fits, less (maybe
    0: no suffix at all) when only part of it does, so it gets elided -
    or None when the name itself doesn't fit (elide the name, no suffix).
    Plain arithmetic, for ModRowDelegate._layout_suffix and the drag pill."""
    if name_w > available:
        return None
    return max(0, min(suffix_w, available - name_w - space_w))


def paint_row_suffix(painter, at: tuple, widget) -> None:
    """The muted suffix after a not-found row's name: `at` is (x, baseline
    y, text) from ModRowDelegate._layout_suffix (or the drag pill), in
    suffix_font and --muted. The caller saves/restores the painter."""
    from PySide6.QtCore import QPointF

    x, baseline, text = at
    painter.setFont(suffix_font(widget))
    painter.setPen(QColor(theme.MUTED))
    painter.drawText(QPointF(x, baseline), text)


def paint_row_warn(painter, at: tuple, widget) -> None:
    """.row-warn: the "!" after a scanned mod's name (and its .dds badge):
    `at` is (x, baseline y) from ModRowDelegate._layout_badge (or the drag
    pill), in issue_font (the row's font, bold: font-weight 700 and no
    font-size of its own) and --warn. The caller saves/restores the
    painter."""
    from PySide6.QtCore import QPointF

    x, baseline = at
    painter.setFont(issue_font(widget))
    painter.setPen(QColor(theme.WARN))
    painter.drawText(QPointF(x, baseline), ROW_WARN_TEXT)


def subscribe_font(widget):
    """.row-subscribe's font: the widget's, SUBSCRIBE_FONT_PX, normal weight."""
    from PySide6.QtGui import QFont

    font = QFont(widget.font())
    font.setPixelSize(SUBSCRIBE_FONT_PX)
    return font


def subscribe_width(widget) -> int:
    """The Subscribe button's border-box width: its text + padding + border.
    (Module level so the check harnesses, which have no real fonts, can
    patch it, as issue_glyph_width.)"""
    from PySide6.QtGui import QFontMetrics

    return QFontMetrics(subscribe_font(widget)).horizontalAdvance(SUBSCRIBE_TEXT) + SUBSCRIBE_SIDES


def paint_subscribe_button(painter, rect, widget, hover: bool, enabled: bool = True) -> None:
    """The .row-subscribe button in `rect` (ModListView.subscribe_rect):
    --panel-2 fill, a 1px --accent border (--muted while `hover`:
    button:hover:not(:disabled) beats button.accent-outline's border
    color), --radius corners clamped to a pill (CSS clamps a radius to half
    the height), "Subscribe" centered in --accent. Not `enabled`
    (button:disabled): the whole button at half opacity, no hover look. The
    caller saves/restores the painter."""
    r = QRectF(rect)
    radius = min(theme.RADIUS, r.height() / 2) - 0.5
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if not enabled:
        painter.setOpacity(painter.opacity() * DISABLED_BUTTON_OPACITY)
    painter.setPen(QPen(QColor(theme.MUTED if hover and enabled else theme.ACCENT), 1))
    painter.setBrush(QColor(theme.PANEL_2))
    # The 1px stroke centered on the half-pixel inset: its outer edge is the rect.
    painter.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.setFont(subscribe_font(widget))
    painter.setPen(QColor(theme.ACCENT))
    painter.drawText(r, Qt.AlignmentFlag.AlignCenter, SUBSCRIBE_TEXT)


def issue_tooltip_text(issues, severity: str, mods: dict) -> str:
    """ModList.jsx RowIssues' icon title: one issue_summary line per issue of
    `severity`. validation_window is imported here, not at the top: it pulls
    in QDialog and friends, which the check harnesses' fake PySide6 lacks."""
    from volt_py.screens.validation_window import issue_summary

    return "\n".join(issue_summary(i, mods) for i in issues if i["severity"] == severity)


class ModListView(QListView):
    """A pane's mod list, over its own ModListModel (`mod_model`). Adds
    ModList.jsx's click-to-deselect (0.3.3): a plain left-click on the
    already-selected row clears the selection; right-click and double-click
    (move between panes) are unaffected.

    Decided on release, not press, as a draggable list's drag starts from a
    press. Qt delivers a double-click's second press as mouseDoubleClickEvent,
    not mousePressEvent, so that re-selects the row the first click just
    deselected before doubleClicked fires (the Electron app's `e.detail === 1`
    equivalent).

    `draggable` (Active only - its order is the load order) adds drag-reorder,
    by hand rather than with Qt's QDrag, matching ModList.jsx (dnd-kit): a
    left press on a row, moved past startDragDistance, selects that row,
    floats the .row-overlay pill (DragOverlay) under the cursor and previews
    the drop - the rows in between slide aside (animated, SlideAnimation),
    the dragged row's card shows faded where it would land (ModRowDelegate).
    A press becomes a drag or a click (select/deselect), never both; a
    draggable list has no drag-select. No auto-scroll at the edges (the wheel
    still scrolls).

    The model is never changed during a drag: the preview is `drag_preview`
    (a DragPreview - two ints), its animation `_slide` (a SlideAnimation) and
    repaints. The one change is at the left
    release: move_row(start, target), and only if the model still holds the
    dragged id at its start row (nothing else changed it meanwhile). Esc,
    focus loss, a lost release or any inconsistency end the drag with no
    change. Showing/moving the overlay window can make Qt deliver other events
    before the call returns, so the state only says "dragging" once everything
    it relies on exists, _end_drag resets the state before anything else, and
    _start_drag ignores nested calls. Qt's implicit mouse grab (the widget
    that got the press gets every move/release until the release) keeps events
    coming outside the list; ShortcutOverride is swallowed mid-drag, so no
    shortcut can change the lists either.

    `matches` (a mod_matches-style callable) gives the pane its search
    (`search`, a PaneSearch; set_search). It is re-applied after every model
    change (reset, insert, remove, move) as ModList.jsx recomputes it on
    every render: hiding mode hides the non-matching rows (setRowHidden),
    so rows - selection, click, double-click - stay model rows. Drag starts
    only while drag_enabled() (never while rows are hidden; a search that
    starts hiding rows mid-press cancels the press/drag, no change).
    `on_search_changed` is called after each re-apply (the pane title's
    count). Without `matches` there is no search at all. `color` (mod id ->
    '#rrggbb' or None) gives the rows their color swatch and the search its
    color filter (set_color_filter). `decor` (mod id -> RowDecor) and
    `tooltip` (mod id -> str) give the rows their decorations and tooltip
    (ModListModel); the screen calls mod_model.refresh_decorations() when
    they change.

    `on_show_issue` (issue key -> None; Active only) makes the rows' issue
    icons (RowDecor.warning / error) live: `issues` (mod id -> that mod's
    validation issues) and `scanned_mods` (() -> the screen's mods, for the
    names in validation_window.issue_summary) give each icon its tooltip,
    and a click on one calls on_show_issue with the first issue of that
    severity (ModList.jsx onShowIssue(list[0].key)). The icon takes the whole
    press - checked before click-to-deselect and drag-reorder ever see it, so
    it never selects, deselects, drags or (as a double-click) moves the row;
    it fires on the left release if that is still over the same icon of the
    same mod, like a button. The pointer turns into a hand over an icon
    (.row-issue { cursor: pointer }).

    `on_subscribe` (mod id -> None; Active only) makes a pending row's
    painted Subscribe button live, through the very same machinery as the
    icons (control_at: an icon, else the button; _issue_press holds the
    kind SUBSCRIBE): taken whole on press, on_subscribe(mod id) on a release
    over the same button of the same mod, the hand cursor, a --muted border
    while hovered (subscribe_hovered), and `subscribe_tooltip()` as its
    tooltip (ModList.jsx .row-subscribe's title). `subscribe_enabled()`
    (ModList.jsx canSubscribe; None = always) false disables it: half
    opacity, no hover look or hand cursor, a click does nothing."""

    # Drag state: None | "pending" (left-pressed on a row, not yet past the
    # drag distance) | "dragging" | "cancelled" (Esc / focus loss; input is
    # ignored until the left button comes up). Class-level so event() can read
    # it even for an event delivered before __init__ has set anything.
    _drag_state: str | None = None
    _drag_starting = False  # inside _start_drag (re-entrancy guard)
    drag_preview: DragPreview | None = None  # set exactly while "dragging"
    _slide: SlideAnimation | None = None  # drag_preview's animation, set with it
    _slide_now = 0.0  # the animation time (ms, _now_ms) the screen shows
    _slide_timer = None  # frame timer while a slide runs (draggable lists only)
    search: PaneSearch | None = None  # the pane's search (set in __init__ if it has one)
    _on_search_changed = None
    # Issue icons (a view with on_show_issue only). _issue_press: the icon a
    # left press landed on, (row, mod id, severity), until its release;
    # _issue_hover: the pointer is over an icon (hand cursor).
    _on_show_issue = None
    _issues = None
    _scanned_mods = None
    _issue_press: tuple[int, str, str] | None = None
    _issue_hover = False
    # The Subscribe button (a view with on_subscribe only): the handler, its
    # tooltip text, and the mod whose button the pointer is over (hover look).
    _on_subscribe = None
    _subscribe_tooltip = None
    _subscribe_enabled = None
    _subscribe_hover: str | None = None

    def __init__(
        self,
        display_name: Callable[[str], str],
        parent: QWidget | None = None,
        *,
        draggable: bool = False,
        name: str = "list",
        matches: Callable[[str, str], bool] | None = None,
        color: Callable[[str], str | None] | None = None,
        on_search_changed: Callable[[], None] | None = None,
        decor: Callable[[str], RowDecor] | None = None,
        tooltip: Callable[[str], str | None] | None = None,
        issues: Callable[[str], list] | None = None,
        on_show_issue: Callable[[str], None] | None = None,
        scanned_mods: Callable[[], dict] | None = None,
        on_subscribe: Callable[[str], None] | None = None,
        subscribe_tooltip: Callable[[], str] | None = None,
        subscribe_enabled: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_show_issue = on_show_issue
        self._on_subscribe = on_subscribe
        self._subscribe_tooltip = subscribe_tooltip
        self._subscribe_enabled = subscribe_enabled
        self._issues = issues
        self._scanned_mods = scanned_mods
        self.draggable = draggable
        self.name = name  # for the action log ("Active", "Inactive")
        # theme.py's mod-list rules (QListView[modList="true"]): set before the
        # first polish. Scoped by property, not by class - a bare QListView rule
        # would also restyle every QComboBox drop-down (also a QListView).
        self.setProperty("modList", True)
        # QListView's default already; the panes assume one selected row.
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.mod_model = ModListModel(display_name, self, color, decor, tooltip)
        if color is not None:
            self.setIconSize(QSize(10, 10))  # .row-color: the 10px swatch
        self.setModel(self.mod_model)  # creates selectionModel(); set once, never replaced
        self.setItemDelegate(ModRowDelegate(self))
        if on_show_issue is not None or on_subscribe is not None:
            # Hover moves over the rows, for the icons' / button's hand cursor
            # (viewportEvent); the ::item:hover card already relies on them.
            self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._deselect_row: int | None = None  # pressed on the selected row; clear on release
        self._press_pos = None
        self._deselected_row: int | None = None  # just cleared by a click; for a double-click
        # Drag (draggable lists only).
        self._drag_row: int | None = None  # pressed/dragged row, at press time
        self._drag_id: str | None = None  # the mod id that was on it
        self._drag_overlay: DragOverlay | None = None
        self._drag_hotspot = QPoint()  # cursor offset inside the overlay pixmap
        self._drag_center_dy = 0  # pill center y - cursor y (viewport px)
        self._drag_probe_x = 0  # an x inside the rows, for indexAt
        self._drag_last_pos: QPoint | None = None  # last cursor pos (viewport)
        self._drag_paint_due = False  # a scroll/re-aim not yet painted synchronously
        if draggable:
            # Paints the slide's frames when no drag move does (_on_slide_tick).
            self._slide_timer = QTimer(self)
            self._slide_timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._slide_timer.setInterval(SLIDE_FRAME_MS)
            self._slide_timer.timeout.connect(self._on_slide_tick)
        # Search (screens with a matcher only).
        self.search = PaneSearch(matches, color) if matches is not None else None
        self._on_search_changed = on_search_changed
        if self.search is not None:
            model = self.mod_model
            # Connected after setModel, so these run after the view's own
            # handling of the change (e.g. reset() dropping hidden rows).
            for signal in (model.modelReset, model.rowsInserted, model.rowsRemoved, model.rowsMoved):
                signal.connect(lambda *_: self._apply_search())

    # ---- search ----
    def set_search(self, *, query: str | None = None, dim: bool | None = None) -> None:
        """The search box's text changed (`query`) or the eye was toggled
        (`dim`): re-applies the search."""
        s = self.search
        if s is None:
            return
        if query is not None:
            s.query = query
        if dim is not None:
            s.dim = dim
        self._apply_search()
        log(
            f"search in {self.name}: {s.query.strip()!r}, {'dimming' if s.dim else 'hiding'} non-matches "
            f"-> [{s.count_text()}]"
        )

    def set_color_filter(self, color: str | None) -> None:
        """Filter by > This mod color ('#rrggbb'), or the hint's Clear (None)."""
        if self.search is None:
            return
        self.search.color_filter = color
        self._apply_search()
        log(f"color filter in {self.name}: {color or 'cleared'} -> [{self.search.count_text()}]")

    def _apply_search(self) -> None:
        """Recomputes the matches over the whole model, hides/shows rows to
        match (hiding mode), repaints (dim mode's marks) and tells the
        screen. A press or drag under way when rows start hiding ends with no
        change (a drag across hidden rows would reorder around them)."""
        s = self.search
        if s is None:
            return
        ids = self.mod_model.ids()
        s.refresh(ids)
        if s.hiding and self._drag_state in ("pending", "dragging"):
            self._end_drag("cancelled", reason="the search started hiding rows")
        for row, mod_id in enumerate(ids):
            hide = s.hidden(mod_id)
            if self.isRowHidden(row) != hide:
                self.setRowHidden(row, hide)
        if self._drag_state == "dragging":
            self._repaint_now()  # dim marks changed under a drag (update() can be starved then)
        else:
            self.viewport().update()
        if self._on_search_changed is not None:
            self._on_search_changed()

    def search_mark(self, row: int) -> str | None:
        """For the delegate: `row`'s dim-mode mark (MARK_MATCH / MARK_DIM),
        None when not dimming (or no such row)."""
        s = self.search
        if s is None or s.matches is None or not s.dim:
            return None
        mod_id = self.mod_model.id_at(row)
        return None if mod_id is None else s.mark(mod_id)

    def drag_enabled(self) -> bool:
        """ModList.jsx dragEnabled = sortable && !hiding: a draggable list,
        with no rows hidden by its search."""
        return self.draggable and not (self.search is not None and self.search.hiding)

    # ---- pane contents ----
    def mod_ids(self) -> list[str]:
        return self.mod_model.ids()

    def set_mod_ids(self, ids) -> None:
        """Repopulates the pane. The selection is cleared first, with its
        signal, as QListWidget.clear() did (a model reset clears it silently)."""
        self.selectionModel().clear()
        self.mod_model.set_ids(ids)

    def selected_mod_id(self) -> str | None:
        indexes = self.selectionModel().selectedIndexes()
        return self.mod_model.id_at(indexes[0].row()) if indexes else None

    def row_label(self, row: int) -> "RowLabel":
        """What the drag pill shows for `row` (ModList.jsx DragOverlay's
        RowLabel): its text (the id if it has none), badge flag, the red
        name (mod_decorations.name_is_red: an outdated or conflicting mod,
        RowLabel's outdated || conflict; a not-found row unless pending) and
        a not-found row's muted suffix (pending / downloading / not found),
        and the trailing .dds badge and "!" warning mark flags."""
        model = self.mod_model
        decor = model.decor_at(row)
        text = model.data(model.index(row, 0)) or model.id_at(row) or ""
        return RowLabel(text, decor.official, name_is_red(decor), name_suffix(decor), decor.dds_leftover,
                        decor.row_warn)

    # ---- issue icons (ModList.jsx RowIssues) ----
    def issue_icons(self, decor: RowDecor, rect) -> list:
        """The issue icons `decor` asks for, on a row painted at item rect
        `rect` (viewport px): (severity, icon name, color, icon rect) left to
        right - warning, then error. They end at the card's right edge less
        .row's 8px padding, the card clipped to the viewport first (as
        _card_rect does for the drag pill), 4px apart; each ISSUE_ICON_PX
        (issue_glyph_width) wide and as tall as the card. Empty when the row has none."""
        shown = [icon for icon in ISSUE_ICONS if getattr(decor, icon[0])]
        if not shown:
            return []
        _left, top, right_margin, bottom = theme.row_margins(self)
        right = min(rect.right(), self.viewport().rect().right()) - right_margin - ROW_PADDING
        subscribe = self.subscribe_rect(decor, rect)
        if subscribe is not None:
            # A pending row with issues (hardly ever: its mod didn't scan):
            # the icons end one .row gap before the button.
            # ponytail: in ModList.jsx both .row-issues and .row-subscribe
            # have margin-left: auto, so flexbox would center the icons in
            # the free space instead; adjacent here. Revisit only if a
            # pending row with issue icons is ever actually seen.
            right = subscribe.left() - 1 - ROW_GAP
        out = []
        x = right + 1  # one past the last icon pixel
        for severity, glyph, color in reversed(shown):
            width = issue_glyph_width(self, glyph)
            x -= width
            out.append((severity, glyph, color, rect.adjusted(x - rect.left(), top, x + width - 1 - rect.right(), -bottom)))
            x -= ISSUE_GAP
        out.reverse()
        return out

    def issue_at(self, pos) -> tuple[int, str] | None:
        """(row, severity) of the issue icon under viewport point `pos`, or
        None - always None for a view without on_show_issue (the Inactive
        pane) or while rows are only previewed (a drag under way)."""
        if self._on_show_issue is None or self.drag_preview is not None:
            return None
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        decor = self.mod_model.decor_at(index.row())
        if not (decor.warning or decor.error):
            return None
        x, y = pos.x(), pos.y()
        for severity, _glyph, _color, r in self.issue_icons(decor, self.visualRect(index)):
            if r.left() <= x <= r.right() and r.top() <= y <= r.bottom():
                return index.row(), severity
        return None

    # ---- the pending rows' Subscribe button (ModList.jsx .row-subscribe) ----
    def subscribe_rect(self, decor: RowDecor, rect):
        """The Subscribe button's rect on a row painted at item rect `rect`
        (viewport px): SUBSCRIBE_HEIGHT tall, vertically centered on the
        card, ending at the card's right edge less .row's 8px padding (the
        card clipped to the viewport first, as issue_icons). None for a row
        that isn't pending, or in a view without on_subscribe."""
        if self._on_subscribe is None or not decor.pending:
            return None
        _left, top, right_margin, bottom = theme.row_margins(self)
        right = min(rect.right(), self.viewport().rect().right()) - right_margin - ROW_PADDING
        left = right - subscribe_width(self) + 1
        card_top, card_h = rect.top() + top, rect.height() - top - bottom
        y = card_top + (card_h - SUBSCRIBE_HEIGHT) // 2
        return rect.adjusted(left - rect.left(), y - rect.top(), right - rect.right(),
                             y + SUBSCRIBE_HEIGHT - 1 - rect.bottom())

    def subscribe_at(self, pos) -> int | None:
        """The row whose Subscribe button is under viewport point `pos`, or
        None - always None without on_subscribe or while rows are only
        previewed (a drag under way), as issue_at."""
        if self._on_subscribe is None or self.drag_preview is not None:
            return None
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        r = self.subscribe_rect(self.mod_model.decor_at(index.row()), self.visualRect(index))
        if r is not None and r.left() <= pos.x() <= r.right() and r.top() <= pos.y() <= r.bottom():
            return index.row()
        return None

    def control_at(self, pos) -> tuple[int, str] | None:
        """(row, kind) of the painted control under `pos`: an issue icon
        (kind: its severity, issue_at) or a Subscribe button (kind
        SUBSCRIBE); None elsewhere. What a press takes whole."""
        hit = self.issue_at(pos)
        if hit is not None:
            return hit
        row = self.subscribe_at(pos)
        return None if row is None else (row, SUBSCRIBE)

    def subscribe_tip(self, pos):
        """For the delegate's helpEvent: (text, button rect) of the Subscribe
        button under `pos` (the text: subscribe_tooltip(), ModList.jsx's
        title on .row-subscribe), or None."""
        row = self.subscribe_at(pos)
        if row is None:
            return None
        rect = self.subscribe_rect(self.mod_model.decor_at(row), self.visualRect(self.mod_model.index(row, 0)))
        return (self._subscribe_tooltip() if self._subscribe_tooltip is not None else SUBSCRIBE_TEXT), rect

    def subscribe_is_enabled(self) -> bool:
        """Whether the Subscribe buttons are usable (ModList.jsx canSubscribe;
        the `subscribe_enabled` callable, else always)."""
        return self._subscribe_enabled is None or bool(self._subscribe_enabled())

    def subscribe_hovered(self, row: int) -> bool:
        """For the delegate: the pointer is over `row`'s Subscribe button (its
        hover look; never mid-drag, never while disabled)."""
        return (self._subscribe_hover is not None and self.drag_preview is None
                and self.subscribe_is_enabled() and self.mod_model.id_at(row) == self._subscribe_hover)

    def _row_issues(self, row: int, severity: str) -> list:
        """`row`'s validation issues of `severity` (the `issues` callable)."""
        mod_id = self.mod_model.id_at(row)
        if mod_id is None or self._issues is None:
            return []
        return [i for i in self._issues(mod_id) or () if i["severity"] == severity]

    def issue_tooltip(self, pos):
        """For the delegate's helpEvent: (text, icon rect) of the issue icon
        under `pos` - that severity's issues, one issue_summary line each -
        or None (not over an icon: the row's own tooltip)."""
        hit = self.issue_at(pos)
        if hit is None:
            return None
        row, severity = hit
        issues = self._row_issues(row, severity)
        if not issues:
            return None
        mods = self._scanned_mods() if self._scanned_mods is not None else {}
        decor = self.mod_model.decor_at(row)
        rect = next(r for s, _g, _c, r in self.issue_icons(decor, self.visualRect(self.mod_model.index(row, 0)))
                    if s == severity)
        return issue_tooltip_text(issues, severity, mods), rect

    def _press_issue(self, event) -> bool:
        """A left press (or double-click) on an issue icon or a Subscribe
        button (control_at): taken whole by the control (True) - remembered
        for its release, nothing else happens. False: not on one, the press
        goes on as usual."""
        hit = self.control_at(event.position().toPoint())
        if hit is None:
            return False
        row, kind = hit
        self._issue_press = (row, self.mod_model.id_at(row), kind)
        return True

    def _release_issue(self, event) -> None:
        """The left release after a control press: if it is still over the
        same control of the same mod (a click), opens the issue / calls
        on_subscribe(mod id); else nothing."""
        (row, mod_id, severity), self._issue_press = self._issue_press, None
        same = self.control_at(event.position().toPoint()) == (row, severity) and self.mod_model.id_at(row) == mod_id
        if severity == SUBSCRIBE:
            if not same:
                log(f"subscribe button: press on {mod_id} released elsewhere, nothing done")
                return
            if not self.subscribe_is_enabled():
                log(f"subscribe button: click on {mod_id} in {self.name}, but the button is disabled (Steam unavailable)")
                return
            log(f"subscribe button: click on {mod_id} in {self.name}")
            self._on_subscribe(mod_id)
            return
        if not same:
            log(f"issue icon: {severity} press on {mod_id} released elsewhere, nothing opened")
            return
        issues = self._row_issues(row, severity)
        if not issues:
            log(f"issue icon: {severity} click on {mod_id}, but it has no such issues any more")
            return
        log(f"issue icon: {severity} click on {mod_id} in {self.name} -> {issues[0]['key']}")
        self._on_show_issue(issues[0]["key"])

    def _update_issue_cursor(self, pos) -> None:
        """The hand cursor over an issue icon or a Subscribe button
        (.row-issue / button { cursor: pointer }), and the button's hover
        look (a repaint when it changes); `pos` None: the pointer left the
        list."""
        hit = self.control_at(pos) if pos is not None and self._drag_state is None else None
        over = hit is not None and (hit[1] != SUBSCRIBE or self.subscribe_is_enabled())  # button:disabled: cursor default
        if over != self._issue_hover:
            self._issue_hover = over
            if over:
                self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.viewport().unsetCursor()
        hover = self.mod_model.id_at(hit[0]) if hit is not None and hit[1] == SUBSCRIBE else None
        if hover != self._subscribe_hover:
            self._subscribe_hover = hover
            self.viewport().update()

    # ---- mouse / keyboard ----
    def mousePressEvent(self, event) -> None:
        if self._issue_press is not None:
            if event.button() != Qt.MouseButton.LeftButton and event.buttons() & Qt.MouseButton.LeftButton:
                return  # another button while the left is held on an icon: swallowed
            self._issue_press = None  # its release never reached us
        if self._press_during_drag(event):
            return
        self._deselect_row = self._deselected_row = None
        if event.button() == Qt.MouseButton.LeftButton and self._press_issue(event):
            return  # the icon's: no select, no deselect, no drag
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            pos = event.position().toPoint()
            index = self.indexAt(pos)
            if index.isValid():
                self._press_pos = pos
                selection = self.selectionModel()
                if selection.isSelected(index) and len(selection.selectedIndexes()) == 1:
                    self._deselect_row = index.row()
                if self.drag_enabled():
                    self._drag_state = "pending"
                    self._drag_row, self._drag_id = index.row(), self.mod_model.id_at(index.row())
        super().mousePressEvent(event)  # selects the pressed row

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._issue_press is not None:
            if event.buttons() & Qt.MouseButton.LeftButton:
                return  # held on an icon: never a drag or a drag-select
            self._issue_press = None  # the release never arrived
        if self._drag_state is not None and not (event.buttons() & Qt.MouseButton.LeftButton):
            self._end_drag(reason="the left release never arrived")
        if self._drag_state == "dragging":
            self._drag_to(pos, event.globalPosition().toPoint())
            return
        if self._drag_state == "cancelled":
            return
        # Moved far enough to be a drag (or drag-select), not a click.
        moved = (
            self._press_pos is not None
            and (pos - self._press_pos).manhattanLength() >= QApplication.startDragDistance()
        )
        if moved:
            self._deselect_row = None
        if self._drag_state == "pending":
            if moved:
                self._start_drag(pos, event.globalPosition().toPoint())
            return  # no drag-select in a draggable list
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._issue_press is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                self._release_issue(event)
            return  # the icon's press never reached the view: nothing to reset
        if self._drag_state is not None:
            if event.button() != Qt.MouseButton.LeftButton:
                return  # another button mid-drag; its press was swallowed too
            was_drag = self._drag_state != "pending"
            self._end_drag(commit=True)  # the drop (a no-op unless "dragging")
            if was_drag:  # this press was a drag: no click, no deselect
                self._deselect_row = None
                super().mouseReleaseEvent(event)  # resets the view's own press state
                return
        row, self._deselect_row = self._deselect_row, None
        super().mouseReleaseEvent(event)
        if row is None or event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.row() == row:
            self.clearSelection()  # selectionChanged -> details panel resets
            self._deselected_row = row

    def mouseDoubleClickEvent(self, event) -> None:
        if self._issue_press is not None:
            if event.button() != Qt.MouseButton.LeftButton and event.buttons() & Qt.MouseButton.LeftButton:
                return
            self._issue_press = None
        if self._press_during_drag(event):
            return
        if event.button() == Qt.MouseButton.LeftButton and self._press_issue(event):
            # A double-click's second press on an icon: another icon press
            # (ModList.jsx stops the icon's dblclick) - never the row's move.
            self._deselected_row = None
            return
        row, self._deselected_row = self._deselected_row, None
        if row is not None and event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid() and index.row() == row:
                self.setCurrentIndex(index)  # re-select, as a plain double-click leaves it
        super().mouseDoubleClickEvent(event)

    def _press_during_drag(self, event) -> bool:
        """A press or double-click while a drag is pending/active/cancelled.
        Another button with the left still down: swallowed (True). Otherwise
        the left release never reached us (e.g. focus was stolen mid-press):
        the stale drag ends with no change and the press goes through (False)."""
        if self._drag_state is None:
            return False
        if (
            event.button() != Qt.MouseButton.LeftButton
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            return True
        self._end_drag(reason="a new press arrived without the left release")
        return False

    def event(self, event) -> bool:
        # While the left button is down on a draggable row, keys stay with the
        # list (keyPressEvent): no app shortcut can change the lists mid-drag.
        if self._drag_state is not None and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def viewportEvent(self, event) -> bool:
        # No context menu while a press/drag is under way (the menu would take
        # the mouse and focus mid-drag); the pane's menu is its viewport's
        # ContextMenu event (customContextMenuRequested).
        if (self._drag_state is not None or self._issue_press is not None) and event.type() == QEvent.Type.ContextMenu:
            event.accept()
            return True
        if self._on_show_issue is not None or self._on_subscribe is not None:
            kind = event.type()
            if kind in (QEvent.Type.HoverEnter, QEvent.Type.HoverMove):
                self._update_issue_cursor(event.position().toPoint())
            elif kind == QEvent.Type.HoverLeave:
                self._update_issue_cursor(None)
        return super().viewportEvent(event)

    def keyPressEvent(self, event) -> None:
        if self._drag_state in ("dragging", "cancelled"):
            if event.key() == Qt.Key.Key_Escape and self._drag_state == "dragging":
                self._end_drag("cancelled", reason="Esc")
            event.accept()  # no keyboard navigation / type-to-search mid-drag
            return
        super().keyPressEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._drag_state == "dragging":
            self._end_drag("cancelled", reason="focus lost")  # e.g. Alt+Tab mid-drag: as if Esc
        super().focusOutEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        # The wheel mid-drag moves the rows under a still cursor: re-aim. No
        # synchronous paint here (a scroll can come from inside a layout pass);
        # the next drag move paints synchronously - Qt's own repaint of the
        # scrolled rows is deferred too, so it can be starved like any other.
        if self._drag_state == "dragging" and self._drag_last_pos is not None:
            self._drag_paint_due = True
            self._update_drag_target(self._drag_last_pos, paint_now=False)

    # ---- drag-reorder (draggable lists only) ----
    def _start_drag(self, pos: QPoint, global_pos: QPoint) -> None:
        """pending -> dragging. A nested call (an event delivered while this
        runs) is ignored. If anything here raises, the half-started drag is
        dropped ("cancelled" until the release) and the error re-raised, so it
        is reported once instead of breaking every later move."""
        if self._drag_starting:
            return
        self._drag_starting = True
        try:
            self._start_drag_steps(pos, global_pos)
        except Exception:
            self._end_drag("cancelled", reason="error while starting the drag")
            raise
        finally:
            self._drag_starting = False

    def _start_drag_steps(self, pos: QPoint, global_pos: QPoint) -> None:
        row, mod_id, model = self._drag_row, self._drag_id, self.mod_model
        if row is None or mod_id is None or model.id_at(row) != mod_id:
            self._end_drag("cancelled", reason="the pressed row changed before the drag started")
            return

        def still_pending(overlay=None) -> bool:
            # Re-checked after every call that may deliver nested events: one
            # of them (e.g. the release) may already have ended this press.
            return (
                self._drag_state == "pending"
                and self._drag_row == row
                and self._drag_id == mod_id
                and self._drag_overlay is overlay
            )

        index = model.index(row, 0)
        if self.currentIndex() != index or not self.selectionModel().isSelected(index):
            self.setCurrentIndex(index)  # the sole selection; the other pane clears
            if not still_pending():
                return
        card = self._card_rect(index)
        # Grab the pill where the row was grabbed (pixmap has a shadow margin).
        hotspot = pos - card.topLeft() + QPoint(DRAG_SHADOW, DRAG_SHADOW)
        size = QSize(card.width() + 2 * DRAG_SHADOW, card.height() + 2 * DRAG_SHADOW)
        overlay = DragOverlay(drag_pill_pixmap(self, self.row_label(row), card.size()), size, self)
        if not still_pending():
            overlay.deleteLater()  # never shown; this press is over
            return
        # Still "pending" until the very end; from here _end_drag (any path)
        # hides and frees the overlay, and nothing sees "dragging" without it.
        self._drag_overlay, self._drag_hotspot = overlay, hotspot
        overlay.move(global_pos - hotspot)
        if not still_pending(overlay):
            return
        overlay.show()  # creates the native window
        if not still_pending(overlay):
            return
        if model.id_at(row) != mod_id:
            self._end_drag("cancelled", reason="the list changed while the drag was starting")
            return
        # The target is the slot under the pill's center (dnd-kit's
        # closestCenter, for same-height rows), not under the cursor.
        self._drag_center_dy = card.top() + card.height() // 2 - pos.y()
        self._drag_probe_x = card.left() + card.width() // 2
        self._drag_last_pos = pos
        self.drag_preview = DragPreview(model.rowCount(), row)
        self._slide = SlideAnimation(self.drag_preview, SLIDE_MS)
        self._slide_now = _now_ms()
        self._drag_state = "dragging"  # last: overlay and preview both set
        log(f"drag start: {mod_id} from {self.name} row {row} ({model.rowCount()} rows)")
        self._repaint_now()  # the dragged row's fade
        self._update_drag_target(pos)

    def _card_rect(self, index):
        """The row's card as drawn: a list-mode row rect is as wide as the
        widest row (long names reach past the pane), so clip it to the
        viewport, then inset by the stylesheet's item margins."""
        rect = self.visualRect(index)
        viewport = self.viewport().rect()
        rect.setLeft(max(rect.left(), viewport.left()))
        rect.setRight(min(rect.right(), viewport.right()))
        left, top, right, bottom = theme.row_margins(self)
        return rect.adjusted(left, top, -right, -bottom)

    def _drag_to(self, pos: QPoint, global_pos: QPoint) -> None:
        overlay = self._drag_overlay
        if overlay is None or self.drag_preview is None:
            # Shouldn't happen (_start_drag only says "dragging" once both
            # exist). If it ever does, stop the drag, unchanged, instead of
            # failing on every move.
            self._end_drag("cancelled", reason="drag state inconsistent (no overlay/preview)")
            return
        overlay.move(global_pos - self._drag_hotspot)  # may deliver nested events
        if self._drag_state == "dragging":  # not ended by one of them
            self._drag_last_pos = pos
            self._update_drag_target(pos)

    def _update_drag_target(self, pos: QPoint, *, paint_now: bool = True) -> None:
        """Re-aims the preview at the slot under the pill (the rows it moves
        start sliding from where they are shown now). Paints a frame, now, if
        the target moved, a scroll left one due, or a slide is under way and
        its next frame is due (a drag move paints the slide's frames itself:
        see _on_slide_tick)."""
        preview = self.drag_preview
        if preview is None:
            return
        target = self._drag_target_row(pos)
        now = max(_now_ms(), self._slide_now)
        slide = self._slide_for(preview)
        frame_due = (
            slide is not None
            and slide.active(self._slide_now)
            and now - self._slide_now >= SLIDE_FRAME_MS
        )
        if target is None:
            changed = False
        elif slide is not None:
            changed = slide.set_target(target, now)
        else:
            changed = preview.set_target(target)
        if not paint_now:
            if changed:
                self._slide_now = now  # later paints show the new legs from their start
                self._drag_paint_due = True
                self.viewport().update()  # in case no drag move follows soon
                self._sync_slide_timer()
        elif changed or self._drag_paint_due or frame_due:
            self._paint_frame(now)

    def _slide_for(self, preview: DragPreview | None) -> SlideAnimation | None:
        slide = self._slide
        return slide if slide is not None and preview is not None and slide.preview is preview else None

    def slot_contents(self, slot: int) -> list[tuple[int, float]] | None:
        """For the delegate: what the drag preview shows in visual slot
        `slot` on the current frame, as (row, position in slots), dragged row
        last - SlideAnimation.contents at the frame's time. None: no drag."""
        preview = self.drag_preview
        if preview is None:
            return None
        slide = self._slide_for(preview)
        if slide is None:
            return [(preview.source_row(slot), float(slot))]
        return slide.contents(slot, self._slide_now)

    def slide_top(self, pos: float) -> int | None:
        """The y (viewport px) of a row rect at fractional slot `pos`:
        between the two slots' real tops. None if either slot doesn't exist."""
        model = self.mod_model
        below = math.floor(pos)
        first = model.index(below, 0)
        if not first.isValid():
            return None
        top = self.visualRect(first).top()
        frac = pos - below
        if frac:
            nxt = model.index(below + 1, 0)
            if not nxt.isValid():
                return None
            top += (self.visualRect(nxt).top() - top) * frac
        return round(top)

    def _paint_frame(self, now: float) -> None:
        """Shows the preview as of `now`: drops finished legs and repaints
        synchronously (_repaint_now); the frame timer runs while any row is
        still sliding."""
        self._slide_now = max(now, self._slide_now)
        slide = self._slide_for(self.drag_preview)
        if slide is not None:
            slide.prune(self._slide_now)
        self._repaint_now()
        self._sync_slide_timer()

    def _sync_slide_timer(self) -> None:
        timer = self._slide_timer
        if timer is None:
            return
        slide = self._slide_for(self.drag_preview)
        running = self._drag_state == "dragging" and slide is not None and slide.active(self._slide_now)
        if running and not timer.isActive():
            timer.start()
        elif not running and timer.isActive():
            timer.stop()

    def _on_slide_tick(self) -> None:
        """A frame of the slide while no drag move paints one: the positions
        are a function of the clock, so a late or missed tick only skips a
        frame, never slows or stalls the slide. Skipped if a drag move
        painted a frame under half a frame ago (unless a scroll left a paint
        due); stops once all rows are at rest (after painting them there) or
        the drag is over."""
        if self._drag_state != "dragging" or self._slide_for(self.drag_preview) is None:
            self._sync_slide_timer()
            return
        now = max(_now_ms(), self._slide_now)
        if self._drag_paint_due or (
            self._slide.active(self._slide_now) and now - self._slide_now >= SLIDE_FRAME_MS / 2
        ):
            self._paint_frame(now)
        else:
            self._sync_slide_timer()

    def _drag_target_row(self, pos: QPoint) -> int | None:
        """The row slot under the pill's center, its y clamped into the
        viewport (outside it -> the first/last visible slot; no auto-scroll).
        Below the last row -> the last; None (keep the target) otherwise."""
        n = self.mod_model.rowCount()
        if n == 0:
            return None
        y = min(max(pos.y() + self._drag_center_dy, 0), self.viewport().height() - 1)
        index = self.indexAt(QPoint(self._drag_probe_x, y))
        if index.isValid():
            return index.row()
        if y < self.visualRect(self.mod_model.index(0, 0)).top():
            return 0
        if y > self.visualRect(self.mod_model.index(n - 1, 0)).bottom():
            return n - 1
        return None

    def _end_drag(self, state: str | None = None, *, commit: bool = False, reason: str = "") -> None:
        """Leaves drag mode (from any state) for `state`: None, or "cancelled"
        to ignore input until the left release. A drag that was under way is
        dropped if `commit` (the left release), else cancelled - no change.
        The state is reset first, since committing and hiding the overlay
        could deliver nested events."""
        overlay, preview, mod_id = self._drag_overlay, self.drag_preview, self._drag_id
        was_dragging = self._drag_state == "dragging"
        self._drag_state = state
        self._drag_overlay = self.drag_preview = self._slide = None
        self._drag_row = self._drag_id = self._drag_last_pos = None
        self._drag_paint_due = False
        self._sync_slide_timer()  # stops it
        if was_dragging:
            if commit:
                self._commit_drag(preview, mod_id)
            else:
                where = f"row {preview.start_row}, preview was row {preview.target_row}" if preview else "no preview"
                log(f"drag cancelled ({reason or 'no reason given'}): {mod_id} stays in {self.name} ({where}), no change")
            self._repaint_now()  # the real order back, no preview
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()

    def _commit_drag(self, preview: DragPreview | None, mod_id: str | None) -> None:
        """The drop - the one real reorder (ModList.jsx onDragEnd's arrayMove):
        move_row(start, target), if the model still holds `mod_id` at the
        start row in a list of the same length (nothing changed it since the
        drag began). Otherwise nothing changes."""
        model = self.mod_model
        if preview is None or mod_id is None:
            log(f"drag drop ignored in {self.name}: no preview/mod recorded, no change")
            return
        start, target = preview.start_row, preview.target_row
        if model.rowCount() != preview.row_count or model.id_at(start) != mod_id:
            log(
                f"drag drop REFUSED in {self.name}: the list changed during the drag "
                f"({preview.row_count} -> {model.rowCount()} rows, row {start} now {model.id_at(start)!r}, "
                f"expected {mod_id!r}); no change"
            )
            return
        if start == target:
            log(f"drag drop: {mod_id} dropped on itself ({self.name} row {start}), no change")
            return
        if model.move_row(start, target):
            log(f"drag drop: {mod_id} {self.name} row {start} -> {target}")
        else:
            log(f"drag drop: move_row({start}, {target}) refused for {mod_id} in {self.name}, no change")

    def _repaint_now(self) -> None:
        """Paints the list synchronously, with its layout brought up to date
        first (paintEvent doesn't lay out). A plain update() is deferred to the
        window's next update request, and while mouse moves keep arriving
        (i.e. the whole time a drag is moving) that request can be starved: on
        real hardware the old QListWidget drag stayed frozen for an entire
        drag while the pill, a synchronous window move, tracked fine. Called
        at drag start/end, once per preview change, and once per slide frame
        (_paint_frame, at most every SLIDE_FRAME_MS) - never per mouse move."""
        self._drag_paint_due = False
        self.executeDelayedItemsLayout()
        self.viewport().repaint()


# ---- drag pill ----

DRAG_SHADOW = 10  # px transparent margin around the drag pill, for its shadow


class RowLabel(NamedTuple):
    """The drag pill's content (ModList.jsx's DragOverlay renders RowLabel
    with the row's mod and `outdated`, but not the dependency props): the
    row's text, whether it shows the official badge, whether the name is
    red (`outdated`: mod_decorations.name_is_red), and a not-found row's
    muted suffix ("(pending)" / "⟳ downloading…"; None: none), whether
    the .dds badge follows the name (RowDecor.dds_leftover) and whether the
    "!" warning mark follows that (RowDecor.row_warn).
    ModListView.row_label."""

    text: str
    official: bool = False
    outdated: bool = False
    suffix: str | None = None
    dds_leftover: bool = False
    row_warn: bool = False


class DragOverlay(QWidget):
    """The floating .row-overlay pill (ModList.jsx's DragOverlay) that follows
    the cursor during a drag. Same window setup as Qt's own drag-image window
    (QShapedPixmapWindow): a frameless tooltip-type window, transparent for
    input, that never takes focus or activation - so the list keeps the mouse
    and the keyboard (Esc) for the whole drag."""

    def __init__(self, pixmap: QPixmap, size: QSize, parent: QWidget) -> None:
        super().__init__(
            parent,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # pill corners + shadow
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._pixmap = pixmap
        self.resize(size)  # logical size (the pixmap is device-pixel-ratio scaled)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()


def drag_pill_pixmap(widget: QWidget, label: RowLabel, size: QSize) -> QPixmap:
    """.row-overlay: --selected fill, 1px --accent border, --radius corners,
    then `label`: the official badge (if any, paint_row_badge) ROW_GAP
    before the mod name, in --text (--danger if outdated), then its muted
    suffix if any (paint_row_suffix) or its .dds badge and / or "!" warning
    mark (paint_row_warn; each ROW_GAP after the previous box, the name
    elided to leave room for them); box-shadow 0 4px
    12px rgba(0,0,0,.5) approximated by stacked translucent rounded rects in
    a transparent margin. No dependency tint (the Electron overlay has none
    either). `size` is the card's (the row rect clipped to the viewport,
    inset by theme.ROW_MARGINS); font and device pixel ratio come from
    `widget`."""
    m = DRAG_SHADOW
    dpr = widget.devicePixelRatioF()
    pixmap = QPixmap(round((size.width() + 2 * m) * dpr), round((size.height() + 2 * m) * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    pill = QRectF(m, m, size.width(), size.height())

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 16))
    shadow = pill.translated(0, 4)
    for spread in range(1, 7):
        r = theme.RADIUS + spread
        painter.drawRoundedRect(shadow.adjusted(-spread, -spread, spread, spread), r, r)

    painter.setPen(QPen(QColor(theme.ACCENT), 1))
    painter.setBrush(QColor(theme.SELECTED))
    painter.drawRoundedRect(pill.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS, theme.RADIUS)

    text_rect = pill.adjusted(9, 0, -9, 0)  # 1px border + .row's 8px side padding
    if label.official:
        font = badge_font(widget)
        badge_w = badge_width(font)
        badge_top = math.floor(pill.center().y() - BADGE_HEIGHT / 2 + 0.5)  # whole px: a crisp border
        paint_row_badge(painter, QRectF(text_rect.left(), badge_top, badge_w, BADGE_HEIGHT), font)
        text_rect.setLeft(text_rect.left() + badge_w + ROW_GAP)
    painter.setPen(QColor(theme.DANGER if label.outdated else theme.TEXT))
    painter.setFont(widget.font())
    metrics = widget.fontMetrics()
    available = max(0, int(text_rect.width()))
    name_room = available
    if label.dds_leftover or label.row_warn:
        # As the row's own (ModRowDelegate._layout_badge): the name's box
        # shrinks to leave ROW_GAP + the badge and / or the "!", which follow it.
        widths = []
        if label.dds_leftover:
            font = badge_font(widget)
            dds_w = badge_width(font, DDS_BADGE_TEXT)
            widths.append(dds_w)
        if label.row_warn:
            widths.append(issue_glyph_width(widget, ROW_WARN_TEXT))
        name_room, xs = trailing_after(metrics.horizontalAdvance(label.text), widths, available)
        if label.dds_leftover:
            badge_top = math.floor(pill.center().y() - BADGE_HEIGHT / 2 + 0.5)
            rect = QRectF(text_rect.left() + xs[0], badge_top, dds_w, BADGE_HEIGHT)
            paint_row_badge(painter, rect, font, DDS_BADGE_TEXT, theme.MUTED)
    elided = metrics.elidedText(label.text, Qt.TextElideMode.ElideRight, name_room)
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
    if label.row_warn:
        # On the name's baseline (inline text), as the suffix's below.
        baseline = text_rect.top() + (text_rect.height() - metrics.height()) / 2 + metrics.ascent()
        paint_row_warn(painter, (text_rect.left() + xs[-1], baseline), widget)
    if label.suffix:
        # As the row's own (ModRowDelegate._layout_suffix): a space, then the
        # muted suffix on the name's baseline, elided first.
        from PySide6.QtGui import QFontMetrics

        suffix_metrics = QFontMetrics(suffix_font(widget))
        name_w, space_w = metrics.horizontalAdvance(label.text), metrics.horizontalAdvance(" ")
        suffix_w = suffix_metrics.horizontalAdvance(label.suffix)
        room = suffix_room(name_w, space_w, suffix_w, available)
        text = (label.suffix if room is not None and room >= suffix_w
                else suffix_metrics.elidedText(label.suffix, Qt.TextElideMode.ElideRight, room) if room
                else "")
        if text:
            baseline = text_rect.top() + (text_rect.height() - metrics.height()) / 2 + metrics.ascent()
            paint_row_suffix(painter, (text_rect.left() + name_w + space_w, baseline, text), widget)
    painter.end()
    return pixmap
