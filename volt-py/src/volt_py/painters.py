"""Circuit painters (design phase 2, memory/DESIGN.md §4): the shared,
cached, device-pixel-aware painting behind VOLT's "Circuit" look.

- dot grid: the window's substrate texture (MainWindow.paintEvent) and the
  inside of an EMPTY mod list / details pane (install_empty_grid): one cached
  tile, blitted with drawTiledPixmap - never a per-dot paint loop.
- panel / card shadow: a cached 9-slice pixmap painted by the host widget
  BEHIND its child panels (install_shadows) - never a QGraphicsEffect on
  anything that contains a mod list (an effect re-renders the whole subtree
  off-screen on every repaint; the drag slide repaints every 10ms).
- terminal labels: TerminalLabel (pane titles: copper mono spaced caps, the
  count in --text, a copper rule under it) and terminal_font (modal titles,
  applied app-wide by icons.VoltStyle.polish).
- copper rail: paint_rail_line / paint_rail_node - the load-order rail's
  line and per-row nodes (lit = enabled, hollow = disabled, square = the
  framework terminal); install_rail / RAIL_ENABLED (+ theme.row_margins) for the
  wiring (step 3.0: the Valheim Active list, coder). Preview:
  `uv run python -m volt_py.painters`.
- keyboard focus ring: a 2px ring just outside a QPushButton (a
  QFocusFrame) only when it got focus from the keyboard (Tab / Backtab / a
  shortcut), never after a mouse click (icons.VoltStyle.polish installs
  the filter on every button).
- motion (phase 4): crossfade (a one-shot snapshot of the outgoing view,
  faded out on a mouse-transparent overlay - the incoming view never gets an
  effect, so it is safe over the mod lists), TabIndicator (the sliding tab
  underline), animate_tabs (both for a QTabWidget), and set_raised's card
  lift (a blend of the two cached shadows). Durations and the on / off
  switch are theme.py's (MOTION*, animations_enabled); every animation here
  falls back to its end state on any error, never blocking the switch.

Screen pixels: Qt at a fractional scale (125%) blends a 1-logical-px line
across two device rows (the phase-1 hardware review). Everything here is
drawn in DEVICE pixels: device_space() switches a painter to 1 unit = 1
device px on a whole-pixel origin, and every size goes through dev().
The pure geometry (dev, dot_spec, shadow_mask, nine_slice, rail_geometry)
has no Qt in it: tools/checks/volt_py_design_phase2.py checks it.
"""

import functools
import math

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPointF, QRect, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QFocusFrame, QLabel, QWidget

from volt_py import theme

# ---- pure geometry (Qt-free) ----


def dev(logical: float, dpr: float) -> int:
    """`logical` px as whole device px at device pixel ratio `dpr`, at least
    1. Rounds x.5 DOWN-ish (floor(v*dpr + 0.25)): a 1px line stays 1 device px
    at 125% (not 2), a 2px one is 2 there (not 3) - a hairline must not grow
    fat just because the scale is fractional."""
    return max(1, int(math.floor(logical * dpr + 0.25)))


# Dot grid (the Circuit mockup: radial dots, 14px pitch, ~2px dots, white 6%
# over the window, 4.5% over a panel).
DOT_PITCH = 14  # logical px
DOT_SIZE = 2  # logical px (a square dot, whole device px)
DOT_ALPHA_WINDOW = 0.06
DOT_ALPHA_PANEL = 0.045


def dot_spec(dpr: float) -> tuple[int, int]:
    """(pitch, dot) in device px: the tile is pitch x pitch with one dot x dot
    square in its top-left corner, so every dot lands on whole device px."""
    return dev(DOT_PITCH, dpr), dev(DOT_SIZE, dpr)


# Panel / card shadow: a Gaussian falloff (CSS box-shadow's blur) around the
# rounded shape, tight enough for the 8px gaps between the main screens'
# panels (GAP = 8): sigma 2.5 -> 3 sigma = 7.5px, offset 2px down.
SHADOW_SIGMA = 2.5  # logical px
SHADOW_EXTENT = 8  # logical px the shadow reaches past the shape (~3 sigma)
SHADOW_OFFSET_Y = 2  # logical px
SHADOW_ALPHA = 0.6  # black, under the shape (box-shadow's color alpha); half that at its edge
# The raised variant (steps 3.2/3.3: a hovered Browse Mods card, the static
# "raised" state; the mockup's box-shadow 0 5px 14px rgba(0,0,0,.72)): the
# same Gaussian, wider, further down, darker. Swapped in by set_raised.
RAISED_SIGMA = 5.5  # logical px
RAISED_EXTENT = 16  # logical px (~3 sigma)
RAISED_OFFSET_Y = 5  # logical px
RAISED_ALPHA = 0.72


def _rounded_rect_distance(px: float, py: float, x0: float, y0: float, x1: float, y1: float, r: float) -> float:
    """Signed distance from (px, py) to the rounded rect [x0, x1] x [y0, y1]
    with corner radius r: > 0 outside, <= 0 inside."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (x1 - x0) / 2 - r, (y1 - y0) / 2 - r
    qx, qy = abs(px - cx) - hx, abs(py - cy) - hy
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - r


def shadow_mask(dpr: float, radius: float = theme.RADIUS, *, raised: bool = False) -> tuple[int, int, int, bytes]:
    """The 9-slice shadow source, device px: (size, corner, extent, alpha)
    where `alpha` is size*size bytes (row-major, 0..255). The shape is a
    rounded rect of width/height 2*r+1 centered in the square; `corner`
    (= extent + r) is each corner slice's side, the one middle row/column is
    what the edges stretch. `raised`: the RAISED_* variant."""
    extent, sigma, peak = ((RAISED_EXTENT, RAISED_SIGMA, RAISED_ALPHA) if raised
                           else (SHADOW_EXTENT, SHADOW_SIGMA, SHADOW_ALPHA))
    ext, r = dev(extent, dpr), dev(radius, dpr)
    sigma = sigma * dpr
    corner = ext + r
    size = 2 * corner + 1
    x0, x1 = ext, size - ext
    out = bytearray(size * size)
    k = 1 / (sigma * math.sqrt(2))
    for y in range(size):
        for x in range(size):
            d = _rounded_rect_distance(x + 0.5, y + 0.5, x0, x0, x1, x1, r)
            a = peak * 0.5 * math.erfc(d * k)  # the Gaussian-blurred edge: 1 inside, .5 at the edge, 0 far out
            out[y * size + x] = max(0, min(255, int(a * 255 + 0.5)))
    return size, corner, ext, bytes(out)


def nine_slice(left: int, top: int, width: int, height: int, size: int, corner: int, ext: int):
    """The 9-slice blits for a shape at device rect (left, top, width,
    height): a list of ((sx, sy, sw, sh), (dx, dy, dw, dh)) - four corners and
    four stretched edges; the center is skipped (the panel covers it). Empty
    when the shape is smaller than its two corners' rounding."""
    r = corner - ext
    mid_w, mid_h = width - 2 * r, height - 2 * r
    if mid_w <= 0 or mid_h <= 0:
        return []
    ox, oy = left - ext, top - ext
    right, bottom = ox + corner + mid_w, oy + corner + mid_h
    c, far = corner, corner + 1  # source: the stretched middle column/row is at index `corner`
    return [
        ((0, 0, c, c), (ox, oy, c, c)),
        ((far, 0, c, c), (right, oy, c, c)),
        ((0, far, c, c), (ox, bottom, c, c)),
        ((far, far, c, c), (right, bottom, c, c)),
        ((c, 0, 1, c), (ox + c, oy, mid_w, c)),
        ((c, far, 1, c), (ox + c, bottom, mid_w, c)),
        ((0, c, c, 1), (ox, oy + c, c, mid_h)),
        ((far, c, c, 1), (right, oy + c, c, mid_h)),
    ]


# The copper load-order rail (the Circuit mockup's .rail / .node): a 2px line
# 8px in from the Active list's left edge, the row cards pushed right by a
# RAIL_GUTTER margin, one node per row centered on the line.
RAIL_ENABLED = True  # the 3.0 wiring switch: False = no rail anywhere (install_rail sets nothing; every rail rule keys off its property)
RAIL_GUTTER = theme.RAIL_GUTTER  # logical px: the rail list's ::item left margin (ROW_MARGINS[0] is 2 without)
RAIL_LEFT = 8  # logical px: the line's left edge in the viewport
RAIL_WIDTH = 2  # logical px
NODE_SIZE = 10  # a round node (live / off), logical px
NODE_BORDER = 2  # the hollow node's ring
TERMINAL_SIZE = 12  # the framework's square terminal
TERMINAL_RADIUS = 2
NODE_GLOW = 6  # a live node's glow (box-shadow 0 0 6px rgba(copper, .6))
NODE_GLOW_ALPHA = 0.6
RAIL_LINE_ALPHA = 0.45
RAIL_LIVE, RAIL_OFF, RAIL_TERMINAL = "live", "off", "terminal"


def rail_geometry(dpr: float) -> tuple[int, int, int]:
    """(line left, line width, center x) in device px from the viewport's
    left edge; the nodes center on `center x`."""
    left, width = dev(RAIL_LEFT, dpr), dev(RAIL_WIDTH, dpr)
    return left, width, left * 2 + width  # center, doubled: callers halve (exact for odd widths too)


def node_sprite_spec(state: str, dpr: float) -> tuple[int, int]:
    """(sprite side, shape side) in device px of a node's cached sprite: the
    shape centered, with room for the live glow around it. The shape takes
    the line's parity (one device px smaller if not), so it centers on the
    line to the whole px (125%: the 15px terminal sat 6|7 around it); the
    glow is cut to what fits between the viewport's left edge and the shape
    (at every scale NODE_GLOW would reach ~2px past it: a hard edge)."""
    _left, width, center2 = rail_geometry(dpr)
    shape = dev(TERMINAL_SIZE if state == RAIL_TERMINAL else NODE_SIZE, dpr)
    shape -= (shape - width) % 2
    pad = min(dev(NODE_GLOW, dpr), (center2 - shape) // 2) if state == RAIL_LIVE else 0
    return shape + 2 * pad, shape


# ---- device-pixel painting ----


def device_space(painter: QPainter) -> tuple[float, float, float, int, int]:
    """Switch `painter` (freshly begun, no world transform) to device pixels:
    1 unit = 1 device px, origin at the widget's own origin rounded to a whole
    device px. Returns (scale, frac_x, frac_y, origin_x, origin_y): a logical
    point (x, y) is at device (x * scale + frac_x, y * scale + frac_y) from
    that origin; origin_x/y is where the origin sits in the window's backing
    store (for a window-wide dot phase)."""
    painter.setWorldTransform(QTransform())
    d = painter.deviceTransform()
    scale = d.m11() or 1.0
    ox, oy = round(d.dx()), round(d.dy())
    inverse, _ok = d.inverted()
    painter.setWorldTransform(QTransform.fromTranslate(ox, oy) * inverse)
    return scale, d.dx() - ox, d.dy() - oy, ox, oy


def device_rect(rect, scale: float, fx: float, fy: float) -> QRect:
    """A logical QRect/QRectF as whole device px (device_space coordinates)."""
    left, top = round(rect.x() * scale + fx), round(rect.y() * scale + fy)
    right = round((rect.x() + rect.width()) * scale + fx)
    bottom = round((rect.y() + rect.height()) * scale + fy)
    return QRect(left, top, right - left, bottom - top)


def _alpha_color(hex_color: str, alpha: float) -> QColor:
    color = QColor(hex_color)
    color.setAlphaF(alpha)
    return color


# ---- dot grid ----


@functools.lru_cache(maxsize=16)
def dot_tile(alpha: float, dpr: float) -> QPixmap:
    """One tile of the dot grid at device scale (devicePixelRatio 1: drawn
    in device_space)."""
    pitch, dot = dot_spec(dpr)
    tile = QPixmap(pitch, pitch)
    tile.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tile)
    painter.fillRect(QRect(0, 0, dot, dot), _alpha_color("#ffffff", alpha))
    painter.end()
    return tile


def paint_dots(painter: QPainter, rect, alpha: float = DOT_ALPHA_WINDOW) -> None:
    """The dot grid over logical `rect` of the painter's widget, phased to the
    window (the grid lines up across every widget that shows it). A clip set
    before the call still applies. Leaves the painter in device space."""
    scale, fx, fy, ox, oy = device_space(painter)
    target = device_rect(rect, scale, fx, fy)
    tile = dot_tile(alpha, scale)
    pitch = tile.width()
    painter.drawTiledPixmap(target, tile, QPoint((ox + target.x()) % pitch, (oy + target.y()) % pitch))


class _EmptyGrid(QObject):
    """install_empty_grid's filter (the target's Paint events only)."""

    def __init__(self, target: QWidget, is_empty, over_default: bool) -> None:
        super().__init__(target)
        self._is_empty = is_empty
        self._over_default = over_default

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.Paint or not self._is_empty():
            return False
        if self._over_default:
            obj.paintEvent(event)  # the frame's own QSS background + border first
        painter = QPainter(obj)
        inner = QRectF(obj.rect()).adjusted(1, 1, -1, -1)  # inside the 1px border
        clip = QPainterPath()
        clip.addRoundedRect(inner, theme.RADIUS - 1, theme.RADIUS - 1)
        painter.setClipPath(clip)
        paint_dots(painter, inner, DOT_ALPHA_PANEL)
        painter.end()
        return self._over_default


def install_empty_grid(target: QWidget, is_empty, *, over_default: bool = False) -> None:
    """Show the dot grid inside `target` whenever `is_empty()` - an empty mod
    list's viewport (over_default False: the viewport's background is filled
    before its Paint event, the rows paint after), or an empty details pane
    (over_default True: a QFrame paints its QSS background in paintEvent, so
    the dots go on top of it). One tiled blit per repaint while empty, one
    cheap is_empty() call otherwise."""
    target.installEventFilter(_EmptyGrid(target, is_empty, over_default))


def list_is_empty(view) -> bool:
    """A mod list shows no rows (none, or the search hides them all): the
    top-left of its viewport hits no row. O(log n), no row walk."""
    return not view.indexAt(QPoint(4, 4)).isValid()


# ---- shadows ----


@functools.lru_cache(maxsize=8)
def shadow_pixmap(dpr: float, raised: bool = False) -> tuple[QPixmap, int, int, int]:
    """(pixmap, size, corner, extent): the cached 9-slice source for `dpr`
    (and the raised variant)."""
    size, corner, ext, alpha = shadow_mask(dpr, raised=raised)
    # Alpha8: an alpha-only image, drawn as black at that alpha. .copy() so
    # the image owns its pixels (not the bytes object).
    image = QImage(alpha, size, size, size, QImage.Format.Format_Alpha8).copy()
    return QPixmap.fromImage(image), size, corner, ext


def paint_shadow(painter: QPainter, rect: QRect, scale: float, fx: float, fy: float, raised: bool = False) -> None:
    """A shadow under logical `rect` (painter already in device_space);
    `raised`: the deeper RAISED_* one."""
    pixmap, size, corner, ext = shadow_pixmap(scale, raised)
    shape = device_rect(QRectF(rect).translated(0, RAISED_OFFSET_Y if raised else SHADOW_OFFSET_Y), scale, fx, fy)
    for (sx, sy, sw, sh), (dx, dy, dw, dh) in nine_slice(shape.x(), shape.y(), shape.width(), shape.height(),
                                                         size, corner, ext):
        painter.drawPixmap(QRect(dx, dy, dw, dh), pixmap, QRect(sx, sy, sw, sh))


class _Shadows(QObject):
    """install_shadows' filter (the host's Paint events only): paints the
    shadows first, then lets the host paint as usual; its children (the
    panels) paint over them."""

    def __init__(self, host: QWidget, targets) -> None:
        super().__init__(host)
        self._host = host
        self._targets = targets

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            host = self._host
            area = event.rect()
            reach = RAISED_REACH
            painter = None
            targets = self._targets() if callable(self._targets) else self._targets
            for target in targets:
                if not target.isVisibleTo(host):
                    continue
                rect = QRect(target.mapTo(host, QPoint(0, 0)), target.size())
                if not rect.adjusted(-reach, -reach, reach, reach).intersects(area):
                    continue
                if painter is None:
                    painter = QPainter(host)
                    scale, fx, fy, _ox, _oy = device_space(painter)
                lift = shadow_lift(target)
                if lift <= 0.0 or lift >= 1.0:
                    paint_shadow(painter, rect, scale, fx, fy, lift >= 1.0)
                else:  # mid-lift (set_raised's animation): the two cached shadows blended
                    painter.setOpacity(1.0 - lift)
                    paint_shadow(painter, rect, scale, fx, fy, False)
                    painter.setOpacity(lift)
                    paint_shadow(painter, rect, scale, fx, fy, True)
                    painter.setOpacity(1.0)
            if painter is not None:
                painter.end()
        return False


RAISED_REACH = max(SHADOW_EXTENT + SHADOW_OFFSET_Y, RAISED_EXTENT + RAISED_OFFSET_Y) + 1  # logical px a shadow can reach past its shape


LIFT_ANIMATION = "voltLift"  # the object name of a target's lift animation (set_raised)


def shadow_lift(target: QWidget) -> float:
    """0 = the rest shadow, 1 = the raised one, between = mid-lift."""
    lift = target.property("lift")
    return float(lift) if isinstance(lift, (int, float)) else 0.0


def _set_lift(target: QWidget, lift: float) -> None:
    target.setProperty("lift", lift)
    parent = target.parentWidget()
    if parent is not None:
        reach = RAISED_REACH
        parent.update(target.geometry().adjusted(-reach, -reach, reach, reach))


def set_raised(target: QWidget, raised: bool) -> None:
    """Lift `target`'s shadow (install_shadows) to the raised variant or back
    - a hovered Browse card (phase 4 M3): the rest and raised cached shadows
    blended over theme.MOTION (css ease; a reversal mid-way takes only the
    remaining share), repainting only the shadow's area (the host paints
    under the target's transparent parent). No effect; the card's QSS hover
    wash and edge stay instant. Animations off / any error: the end state
    at once."""
    end = 1.0 if raised else 0.0
    start = shadow_lift(target)
    try:
        animation = target.findChild(QVariantAnimation, LIFT_ANIMATION)
        if animation is not None:
            animation.stop()
        if start == end:
            return
        if not theme.animations_enabled():
            _set_lift(target, end)
            return
        if animation is None:
            animation = QVariantAnimation(target)
            animation.setObjectName(LIFT_ANIMATION)
            animation.setEasingCurve(css_ease())
            animation.valueChanged.connect(lambda value, target=target: _set_lift(target, float(value)))
        animation.setDuration(max(1, round(theme.MOTION * abs(end - start))))
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()
    except Exception:
        _set_lift(target, end)


def install_shadows(host: QWidget, targets) -> None:
    """Paint a Circuit panel shadow under each of `targets` (widgets inside
    `host`, or a callable returning them - e.g. the Browse window's current
    cards), from `host`'s paint: a cached 9-slice, eight small blits per
    panel per repaint of that area. The panels themselves (mod lists
    included) are untouched - no effect, no off-screen render."""
    host.installEventFilter(_Shadows(host, targets))


# ---- terminal labels ----

TERMINAL_SPACING = 0.16  # em (the mockup's pane titles: letter-spacing .16em, 11px)
TERMINAL_MODAL_SPACING = 0.14  # em (modal titles: .14em at 13px)
TERMINAL_PANE_PX = 11
TERMINAL_MODAL_PX = 13
TERMINAL_RULE_ALPHA = 0.45  # the copper rule under a pane title (--sig-line)
TERMINAL_RULE_INSET = 60  # logical px each side (margin: 0 60px)
TERMINAL_GROUP_PX = 10  # an action-column group label (step 3.1): 10px, .14em, a side rule
TERMINAL_GROUP_SPACING = 0.14
TERMINAL_SIDE_GAP = 6  # logical px between a group label's text and its side rule
TERMINAL_KEY_PX = 11  # a details-pane key (step 3.1; QSS px sizes are whole, the mockup's 10.5 -> 11)
TERMINAL_KEY_SPACING = 0.14
TERMINAL_HEADING_SPACING = 0.16  # a dialog heading (step 3.4: Rules / Warnings): the side-rule label at 11px, .16em
TERMINAL_CAPTION_SPACING = 0.2  # the game-select caption (step 3.4): 11px, .2em, a rule both sides
TERMINAL_CAPTION_GAP = 14  # logical px between that caption's text and each rule


def terminal_font(size_px: int, spacing_em: float) -> QFont:
    """The attributes QSS can't set - letter-spacing and ALL CAPS - on an
    otherwise empty font, so the widget's QSS family / size / weight / color
    still apply on top (a QSS font rule only overrides what it names)."""
    font = QFont()
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, round(size_px * spacing_em, 2))
    return font


def is_terminal_font(font: QFont, size_px: int, spacing_em: float) -> bool:
    return (font.capitalization() == QFont.Capitalization.AllUppercase
            and abs(font.letterSpacing() - round(size_px * spacing_em, 2)) < 0.01)


class TerminalLabel(QLabel):
    """A Circuit terminal label: a pane title in copper mono spaced caps
    (theme.py's QLabel[role="pane-title"] rule sets family / size / weight),
    a trailing " [count]" in --text, and (`rule`) a copper hairline under it,
    inset TERMINAL_RULE_INSET each side, in whole device px. rule="side" is
    the action column's group label (step 3.1): 10px, left-aligned, the
    hairline running from TERMINAL_SIDE_GAP after the text to the right
    edge, on the text's vertical center; rule="heading" is the same side
    rule at the pane-title size (a dialog heading, step 3.4), and with
    setWordWrap(True) a heading too wide for the label wraps (no rule then);
    rule="both" is centred text with a rule from each edge to
    TERMINAL_CAPTION_GAP before / after it (the game-select caption).
    text() is the plain "Title [N]" the screens set - only the painting
    changes."""

    def __init__(self, text: str = "", *, rule: bool | str = True, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "pane-title")
        self.setProperty("rule", rule)
        self._rule = rule
        if rule == "side":
            self.setFont(terminal_font(TERMINAL_GROUP_PX, TERMINAL_GROUP_SPACING))
        elif rule == "heading":
            self.setProperty("rule", "side")
            self.setProperty("size", "pane")  # theme.py: the 11px side-rule label
            self._rule = "side"
            self.setFont(terminal_font(TERMINAL_PANE_PX, TERMINAL_HEADING_SPACING))
        elif rule == "both":
            self.setFont(terminal_font(TERMINAL_PANE_PX, TERMINAL_CAPTION_SPACING))
        else:
            self.setFont(terminal_font(TERMINAL_PANE_PX, TERMINAL_SPACING))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        text = self.text()
        title, bracket, rest = text.partition(" [")
        count = f" [{rest}" if bracket else ""
        font = self.font()
        metrics = QFontMetricsF(font)
        area = QRectF(self.contentsRect())
        title_w, count_w = metrics.horizontalAdvance(title), metrics.horizontalAdvance(count)
        if self.wordWrap() and title_w + count_w > area.width():
            # too wide for one line (a long dialog heading): wrapped as the
            # label laid it out (same font), no rule
            painter.setFont(font)
            painter.setPen(QColor(theme.SIGNAL))
            painter.drawText(area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, text)
            painter.end()
            return
        if self._rule == "both" or self.alignment() & Qt.AlignmentFlag.AlignHCenter:
            x = area.left() + max(0.0, (area.width() - title_w - count_w) / 2)
        else:
            x = area.left()
        painter.setFont(font)
        painter.setPen(QColor(theme.SIGNAL))
        painter.drawText(QRectF(x, area.top(), max(0.0, area.right() - x), area.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        if count:
            painter.setPen(QColor(theme.TEXT))
            painter.drawText(QRectF(x + title_w, area.top(), max(0.0, area.right() - x - title_w), area.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, count)
        if self._rule == "both":
            scale, fx, fy, _ox, _oy = device_space(painter)
            color = _alpha_color(theme.SIGNAL, TERMINAL_RULE_ALPHA)
            end = x + title_w + count_w + TERMINAL_CAPTION_GAP
            for left, right in ((0.0, x - TERMINAL_CAPTION_GAP), (end, float(self.width()))):
                line = device_rect(QRectF(left, area.center().y(), max(0.0, right - left), 1), scale, fx, fy)
                line.setHeight(dev(1, scale))
                if line.width() > 0:
                    painter.fillRect(line, color)
        elif self._rule == "side":
            scale, fx, fy, _ox, _oy = device_space(painter)
            start = x + title_w + count_w + TERMINAL_SIDE_GAP
            line = device_rect(QRectF(start, area.center().y(), max(0.0, self.width() - start), 1), scale, fx, fy)
            line.setHeight(dev(1, scale))
            if line.width() > 0:
                painter.fillRect(line, _alpha_color(theme.SIGNAL, TERMINAL_RULE_ALPHA))
        elif self._rule:
            scale, fx, fy, _ox, _oy = device_space(painter)
            inset = TERMINAL_RULE_INSET if self.alignment() & Qt.AlignmentFlag.AlignHCenter else 0
            width = self.width() - 2 * inset
            if width < 40:  # a narrow pane: the rule spans the label instead
                inset, width = 0, self.width()
            line = device_rect(QRectF(inset, self.height() - 1, width, 1), scale, fx, fy)
            line.setHeight(dev(1, scale))
            painter.fillRect(line, _alpha_color(theme.SIGNAL, TERMINAL_RULE_ALPHA))
        painter.end()


# ---- the details pane's thumbnail frame (step 3.1) ----

THUMB_TICKS = True  # the copper corner ticks (user-approved §3b item); False = the plain mat fallback
THUMB_PAD = 6  # logical px of --well mat between the 1px border and the image
THUMB_RADIUS = 4
THUMB_TICK = 8  # an L tick's arm, logical px
THUMB_TICK_W = 2  # its stroke
THUMB_TICK_OUT = 4  # how far a tick starts outside the mat's corner
# The widget's margins around the mat: room for the ticks (4) and the cached
# panel shadow under it (SHADOW_EXTENT 8, offset 2 down: 6 above, 10 below).
THUMB_MARGINS = (SHADOW_EXTENT, SHADOW_EXTENT - SHADOW_OFFSET_Y, SHADOW_EXTENT, SHADOW_EXTENT + SHADOW_OFFSET_Y)


def thumb_chrome() -> tuple[int, int]:
    """(width, height) the frame adds around its image, logical px."""
    left, top, right, bottom = THUMB_MARGINS
    mat = 2 * (THUMB_PAD + 1)
    return left + right + mat, top + bottom + mat


def thumb_ticks(left: int, top: int, right: int, bottom: int, dpr: float) -> list[tuple[int, int, int, int]]:
    """The four copper L ticks around a mat whose device-px edges are
    left/top (first px) and right/bottom (one past the last), as (x, y, w, h)
    device rects: each corner an arm along x and one along y, starting
    THUMB_TICK_OUT outside the corner (the mockup's 8x8 box at -4,-4 with a
    2px border on its two outer sides). Qt-free."""
    out, arm, w = dev(THUMB_TICK_OUT, dpr), dev(THUMB_TICK, dpr), dev(THUMB_TICK_W, dpr)
    rects = []
    for horizontal_x, vertical_x in ((left - out, left - out), (right + out - arm, right + out - w)):
        for horizontal_y, vertical_y in ((top - out, top - out), (bottom + out - w, bottom + out - arm)):
            rects.append((horizontal_x, horizontal_y, arm, w))
            rects.append((vertical_x, vertical_y, w, arm))
    return rects


class ThumbFrame(QWidget):
    """The Valheim details pane's package icon on a recessed mat (step 3.1):
    the cached panel shadow, a --well mat with a 1px --border edge, the
    image, and (THUMB_TICKS) a copper L tick on each corner - one static
    paint, in whole device px, repainted only when the widget is (resize /
    a new mod); never over a list. set_image(pixmap, box) shows `pixmap`
    at its own size, shrunk (never grown) to fit `box` (logical px)."""

    def __init__(self, parent: QWidget | None = None, *, empty_mat: bool = False) -> None:
        super().__init__(parent)
        self._source: QPixmap | None = None
        self._w = self._h = 0
        # empty_mat (Browse Mods' detail header, 3.3): with no image (loading,
        # none, a failed fetch) the frame keeps the box's size and paints the
        # bare mat + ticks - no layout jump when the icon arrives.
        self._empty_mat = empty_mat

    def set_image(self, pixmap: QPixmap | None, box_w: int, box_h: int) -> None:
        if pixmap is not None and pixmap.isNull():
            pixmap = None
        self._source = pixmap
        w, h = (pixmap.width(), pixmap.height()) if pixmap is not None else ((box_w, box_h) if self._empty_mat else (0, 0))
        if w > 0 and h > 0 and (w > box_w or h > box_h):
            f = max(0.0, min(box_w / w, box_h / h))
            w, h = int(w * f), int(h * f)
        self._w, self._h = w, h
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        cw, ch = thumb_chrome()
        return QSize(self._w + cw, self._h + ch)

    minimumSizeHint = sizeHint

    def paintEvent(self, event) -> None:
        if (self._source is None and not self._empty_mat) or self._w <= 0 or self._h <= 0:
            return
        left, top, _right, _bottom = THUMB_MARGINS
        chrome = 2 * (THUMB_PAD + 1)
        mat = QRect(left, top, self._w + chrome, self._h + chrome)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale, fx, fy, _ox, _oy = device_space(painter)
        paint_shadow(painter, mat, scale, fx, fy)
        box = device_rect(mat, scale, fx, fy)
        edge, radius = dev(1, scale), THUMB_RADIUS * scale
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.BORDER))
        painter.drawRoundedRect(QRectF(box), radius, radius)
        painter.setBrush(QColor(theme.WELL))
        painter.drawRoundedRect(QRectF(box.adjusted(edge, edge, -edge, -edge)), radius - edge, radius - edge)
        if self._source is not None:
            image = device_rect(QRectF(left + THUMB_PAD + 1, top + THUMB_PAD + 1, self._w, self._h), scale, fx, fy)
            painter.drawPixmap(image, self._source)
        if THUMB_TICKS:
            copper = QColor(theme.SIGNAL)
            for x, y, w, h in thumb_ticks(box.left(), box.top(), box.left() + box.width(), box.top() + box.height(), scale):
                painter.fillRect(QRect(x, y, w, h), copper)
        painter.end()


# ---- the copper rail (component; wiring: the phase-2 report's plug-in spec) ----


def paint_rail_line(painter: QPainter, viewport_rect) -> None:
    """The rail's line down the full height of logical `viewport_rect` (the
    Active list's viewport; paint it before the rows). Leaves the painter in
    device space."""
    scale, fx, fy, _ox, _oy = device_space(painter)
    left, width, _center2 = rail_geometry(scale)
    area = device_rect(viewport_rect, scale, fx, fy)
    painter.fillRect(QRect(area.x() + left, area.y(), width, area.height()),
                     _alpha_color(theme.SIGNAL, RAIL_LINE_ALPHA))


@functools.lru_cache(maxsize=16)
def node_sprite(state: str, dpr: float) -> QPixmap:
    """A node's cached sprite at device scale: live = copper disc + glow,
    off = hollow ring (--muted ring, --panel fill), terminal = copper square."""
    side, shape = node_sprite_spec(state, dpr)
    sprite = QPixmap(side, side)
    sprite.fill(Qt.GlobalColor.transparent)
    painter = QPainter(sprite)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = side / 2
    if state == RAIL_LIVE:
        glow = QRadialGradient(c, c, c)
        glow.setColorAt(shape / 2 / c, _alpha_color(theme.SIGNAL, NODE_GLOW_ALPHA))
        glow.setColorAt(1.0, _alpha_color(theme.SIGNAL, 0.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(QRectF(0, 0, side, side))
    box = QRectF(c - shape / 2, c - shape / 2, shape, shape)
    if state == RAIL_TERMINAL:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SIGNAL))
        radius = dev(TERMINAL_RADIUS, dpr)
        painter.drawRoundedRect(box, radius, radius)
    elif state == RAIL_LIVE:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SIGNAL))
        painter.drawEllipse(box)
    else:
        ring = dev(NODE_BORDER, dpr)
        painter.setPen(QPen(QColor(theme.MUTED), ring))
        painter.setBrush(QColor(theme.PANEL))
        painter.drawEllipse(box.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2))
    painter.end()
    return sprite


def paint_rail_node(painter: QPainter, row_rect, state: str) -> None:
    """One row's node, centered on the rail line at logical `row_rect`'s
    vertical center (the row's item rect in viewport coordinates, x ignored).
    Leaves the painter in device space. A cached sprite blit: cheap per
    visible row, also during the drag slide's 10ms repaints."""
    scale, fx, fy, _ox, _oy = device_space(painter)
    left, _width, center2 = rail_geometry(scale)
    sprite = node_sprite(state, scale)
    side = sprite.width()
    area = device_rect(row_rect, scale, fx, fy)
    x = round(center2 / 2 - side / 2)
    y = round(area.y() + area.height() / 2 - side / 2)
    painter.drawPixmap(QPoint(area.x() + x, y), sprite)


class _RailLine(QObject):
    """install_rail's filter (the viewport's Paint events): the line, under
    the rows (the viewport's background is filled before its Paint event)."""

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Paint:
            painter = QPainter(obj)
            paint_rail_line(painter, QRectF(obj.rect()))
            painter.end()
        return False


def install_rail(view) -> None:
    """Give mod list `view` the copper rail (no-op while RAIL_ENABLED is
    False): the rail="true" property (theme.py's gutter ::item rule;
    theme.row_margins), repolished in case the view was polished already, and the
    line down its viewport. The nodes are the row delegate's
    (paint_rail_node)."""
    if not RAIL_ENABLED:
        return
    view.setProperty("rail", True)
    view.style().unpolish(view)
    view.style().polish(view)
    viewport = view.viewport()
    viewport.installEventFilter(_RailLine(viewport))


# ---- keyboard focus ring ----

FOCUS_RING = 2  # logical px
KEYBOARD_REASONS = (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)


class _RingFrame(QFocusFrame):
    """The ring itself: a QFocusFrame (Qt's own "focus frame outside the
    widget" overlay - it follows the widget's geometry and stacking, and the
    style masks it to the PM_FocusFrameH/VMargin band around the widget, 2px
    under Fusion), painted as a rounded 2px --accent-hover ring."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale, fx, fy, _ox, _oy = device_space(painter)
        box = QRectF(device_rect(QRectF(self.rect()), scale, fx, fy))
        ring = dev(FOCUS_RING, scale)
        radius = (theme.RADIUS + FOCUS_RING) * scale
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme.ACCENT_HOVER), ring))
        painter.drawRoundedRect(box.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2), radius, radius)
        painter.end()

    # QFocusFrame re-applies the style's focus-frame mask whenever the
    # button moves / resizes; Fusion's mask is the square 2px band, which cut
    # the ring's rounded corners out (hardware check, 0.5.7). The ring paints
    # only the 2px band outside the button, so it needs no mask; it sits ABOVE
    # the button, in the window / scroll viewport (icons.VoltStyle.styleHint
    # SH_FocusFrame_AboveWidget, 0.5.12: a button-high parent such as a
    # QMessageBox's button box clipped its top / bottom), and QFocusFrame is
    # transparent to the mouse already.
    def setWidget(self, widget) -> None:
        super().setWidget(widget)
        self.clearMask()

    def eventFilter(self, obj, event) -> bool:
        handled = super().eventFilter(obj, event)
        if not self.mask().isEmpty():
            self.clearMask()
        return handled


class FocusRing(QObject):
    """One app-wide filter, installed on every QPushButton by
    icons.VoltStyle.polish (only buttons' events pass through it): a FocusIn
    from the keyboard (Tab / Backtab / a shortcut - Qt's :focus-visible)
    puts the ring (_RingFrame) around the button; focus loss or a mouse
    press takes it away, so a click never leaves a ring. The ring sits in
    the 2px just outside the button: its own look (primary fill included)
    is untouched."""

    def __init__(self) -> None:
        super().__init__()
        self._frame: _RingFrame | None = None

    def _ring(self) -> "_RingFrame":
        # The frame lives in the focused widget's parent (setWidget reparents
        # it), so it dies with that dialog / screen: make a new one then.
        if self._frame is None or not shiboken_valid(self._frame):
            self._frame = _RingFrame()
        return self._frame

    def eventFilter(self, obj, event) -> bool:
        kind = event.type()
        # The window attribute is Qt's own "focus moved by a real Tab key /
        # shortcut" flag: a dialog's initial focus also arrives as
        # TabFocusReason (QApplication::setActiveWindow), and must not ring.
        if (kind == QEvent.Type.FocusIn and event.reason() in KEYBOARD_REASONS
                and obj.window().testAttribute(Qt.WidgetAttribute.WA_KeyboardFocusChange)):
            self._ring().setWidget(obj)
        elif kind in (QEvent.Type.FocusOut, QEvent.Type.MouseButtonPress):
            frame = self._frame
            if frame is not None and shiboken_valid(frame) and frame.widget() is obj:
                frame.setWidget(None)
        return False


def shiboken_valid(obj) -> bool:
    """False once Qt deleted the C++ object behind a Python wrapper."""
    from shiboken6 import isValid

    return isValid(obj)


FOCUS_RING_FILTER: FocusRing | None = None


def focus_ring() -> FocusRing:
    """The one shared FocusRing (created on first use, app-lived)."""
    global FOCUS_RING_FILTER
    if FOCUS_RING_FILTER is None:
        FOCUS_RING_FILTER = FocusRing()
    return FOCUS_RING_FILTER


# ---- motion (phase 4: memory/DESIGN.md §27-28) ----


def css_ease() -> QEasingCurve:
    """CSS `ease` = cubic-bezier(0.25, 0.1, 0.25, 1) (the game-select tile's curve)."""
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.25, 0.1), QPointF(0.25, 1.0), QPointF(1.0, 1.0))
    return curve


class _FadeOverlay(QWidget):
    """crossfade's top layer: `pixmap` (or a flat `fill`) over `rect` of
    `host`, fading 1 -> 0 over `duration` ms, then deleted. Transparent to
    the mouse and never focused, so what is under it (a mod list included)
    is live from the first frame; it paints with QPainter opacity - no
    QGraphicsEffect anywhere."""

    def __init__(self, host: QWidget, rect: QRect, duration: int, pixmap=None, fill: str | None = None) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if pixmap is not None:
            pixmap.setDevicePixelRatio(1.0)  # painted in device_space
        self._pixmap, self._fill, self._opacity = pixmap, fill, 1.0
        self.setGeometry(rect)
        self.raise_()
        self.show()
        self._animation = animation = QVariantAnimation(self)
        animation.setDuration(duration)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(css_ease())
        animation.valueChanged.connect(self._step)
        animation.finished.connect(self.deleteLater)
        animation.start()

    def _step(self, value) -> None:
        self._opacity = float(value)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        scale, fx, fy, _ox, _oy = device_space(painter)
        if self._pixmap is not None:
            # 1 grabbed px = 1 device px at the overlay's whole-px origin: no resampling blur at 125%
            painter.drawPixmap(QPoint(0, 0), self._pixmap)
        else:
            painter.fillRect(device_rect(QRectF(self.rect()), scale, fx, fy), QColor(self._fill))
        painter.end()


def stop_fades(host: QWidget) -> None:
    """Ends every crossfade / fade_in running on `host` at once (their end
    state: the live view). Never raises."""
    try:
        for overlay in host.children():
            if isinstance(overlay, _FadeOverlay):
                overlay.hide()
                overlay.deleteLater()
    except Exception:
        pass


def crossfade(host: QWidget, swap, duration: int = theme.MOTION, rect: QRect | None = None) -> None:
    """Run `swap()` (the real, instant switch: a stack page, a central
    widget, a tab) with a crossfade over `rect` of `host` (default: all of
    it) - phase 4 M1. The outgoing view is grabbed ONCE from the window (so
    the dot grid and every background come along), `swap()` runs, and the
    snapshot fades out on a _FadeOverlay above the incoming view. The
    incoming view is never touched: no opacity effect over a mod list, which
    stays live and draggable underneath. Animations off, a hidden host or
    any error: just `swap()`. `swap()` itself runs exactly once and its own
    errors are the caller's."""
    area = rect if rect is not None else QRect(QPoint(0, 0), host.size())
    snapshot = None
    try:
        if theme.animations_enabled() and host.isVisible() and not area.isEmpty():
            window = host.window()
            snapshot = window.grab(QRect(host.mapTo(window, area.topLeft()), area.size()))
            if snapshot.isNull():
                snapshot = None
    except Exception:
        snapshot = None
    if snapshot is not None:
        stop_fades(host)  # the snapshot already holds a running fade's frame: replace it, never stack
    swap()
    if snapshot is not None:
        try:
            _FadeOverlay(host, area, duration, pixmap=snapshot)
        except Exception:
            pass


def fade_in(host: QWidget, fill: str, duration: int = theme.MOTION_FAST) -> None:
    """A flat `fill` over `host` fading out: the stand-in crossfade where the
    outgoing view can't be grabbed before the switch (a QTabWidget page
    changed from the keyboard). Same rules as crossfade."""
    try:
        if theme.animations_enabled() and host.isVisible():
            stop_fades(host)
            _FadeOverlay(host, QRect(QPoint(0, 0), host.size()), duration, fill=fill)
    except Exception:
        pass


TAB_UNDERLINE = 2  # logical px: the selected tab's --accent underline
TAB_RULE = 1  # logical px: the tab row's --border rule


class TabIndicator(QWidget):
    """The selected tab's 2px --accent underline, on a mouse-transparent
    overlay over the whole tab row `host` (phase 4 M2): it slides (x and
    width, OutCubic over theme.MOTION_SLIDE) from where it is to the new tab
    on moved(animate=True), and snaps otherwise. `band()` returns the
    current tab's border box in `host` coordinates (bottom = the underline's
    bottom edge), or None - read live at every paint, so a resize, a tab
    text change ("Required (3)") or a hidden tab moves it with no bookkeeping.
    The selected tab's own QSS underline is transparent (theme.py), so this
    also paints the 1px --border rule under it (hidden under the underline
    at rest, visible mid-slide). Whole device px; hover underlines stay QSS
    (instant)."""

    def __init__(self, host: QWidget, band) -> None:
        super().__init__(host)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._band = band
        self._from: QRectF | None = None  # where a slide started (logical)
        self._t = 1.0
        self._shown: QRectF | None = None  # the underline last painted (logical)
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._step)
        self._animation.finished.connect(self._settle)
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.raise_()
        self.show()

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def moved(self, animate: bool = True) -> None:
        """The current tab changed (call after the change)."""
        try:
            self._animation.stop()
            if animate and self._shown is not None and theme.animations_enabled():
                self._from, self._t = QRectF(self._shown), 0.0
                self._animation.setDuration(theme.MOTION_SLIDE)
                self._animation.start()
            else:
                self._settle()
        except Exception:
            self._settle()
        self.raise_()
        self.update()

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def _settle(self) -> None:
        self._from, self._t = None, 1.0
        self.update()

    def paintEvent(self, event) -> None:
        target = self._band()
        if target is None or target.isEmpty():
            self._shown = None
            return
        target = QRectF(target)
        x, width = target.x(), target.width()
        if self._from is not None:
            t = self._t
            x = self._from.x() + (x - self._from.x()) * t
            width = self._from.width() + (width - self._from.width()) * t
        bottom = target.y() + target.height()
        self._shown = QRectF(x, target.y(), width, target.height())
        painter = QPainter(self)
        scale, fx, fy, _ox, _oy = device_space(painter)
        base = round(bottom * scale + fy)  # the underline's bottom edge, device px
        rule = device_rect(QRectF(target.x(), 0, target.width(), 1), scale, fx, fy)
        rule_h = dev(TAB_RULE, scale)
        painter.fillRect(QRect(rule.x(), base - rule_h, rule.width(), rule_h), QColor(theme.BORDER))
        line = device_rect(QRectF(x, 0, width, 1), scale, fx, fy)
        line_h = dev(TAB_UNDERLINE, scale)
        painter.fillRect(QRect(line.x(), base - line_h, line.width(), line_h), QColor(theme.ACCENT))
        painter.end()


def animate_tabs(tabs, page_fill: str = theme.PANEL_2) -> "TabIndicator | None":
    """Phase 4 for a QTabWidget (both Settings windows): the sliding
    underline (a TabIndicator on its tab bar, the tab's border box less the
    SETTINGS_TABS_GAP bottom margin) and the page crossfade over
    theme.MOTION_FAST - a click is grabbed before the page changes
    (tabBarClicked comes first; the bar's own switch is then a no-op), a
    keyboard switch (Ctrl+Tab, arrows) has no such signal and fades in from
    the pane's `page_fill`. Call before adding the tabs. Any error: plain
    tabs, as before."""
    try:
        bar = tabs.tabBar()
        gap = theme.SETTINGS_TABS_GAP

        def band():
            index = bar.currentIndex()
            if index < 0:
                return None
            r = bar.tabRect(index)
            return QRect(r.x(), r.y(), r.width(), r.height() - gap)

        indicator = TabIndicator(bar, band)
        clicking = [False]

        def page_area():
            page = tabs.currentWidget()
            return page.parentWidget() if page is not None else None

        def clicked(index: int) -> None:
            area = page_area()
            # tabBarClicked also fires for a right / middle click, which Qt itself ignores
            if (area is None or index < 0 or index == tabs.currentIndex() or not tabs.isTabEnabled(index)
                    or not QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                return
            clicking[0] = True
            try:
                crossfade(area, lambda: tabs.setCurrentIndex(index), theme.MOTION_FAST)
            finally:
                clicking[0] = False

        def changed(_index: int) -> None:
            indicator.moved(True)
            area = page_area()
            if not clicking[0] and area is not None:
                fade_in(area, page_fill)

        bar.tabBarClicked.connect(clicked)
        tabs.currentChanged.connect(changed)
        return indicator
    except Exception:
        return None


# ---- standalone preview: `uv run python -m volt_py.painters` ----


def _preview() -> None:  # pragma: no cover - a real-hardware look, not a test
    import sys

    from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QMessageBox, QPushButton, QVBoxLayout

    from volt_py import icons
    from volt_py.theme import apply_theme

    app = QApplication(sys.argv)
    apply_theme(app)

    class Rail(QWidget):
        """A stand-in Active list: the rail, a node per row, row cards in the gutter."""

        ROWS = (("BepInExPack_Valheim", RAIL_TERMINAL), ("Jotunn", RAIL_LIVE), ("BuildOnShip", RAIL_OFF),
                ("EpicLoot", RAIL_LIVE), ("ValheimRAFT", RAIL_LIVE))

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.fillRect(self.rect(), QColor(theme.PANEL))
            painter.end()
            painter = QPainter(self)
            paint_rail_line(painter, QRectF(self.rect()))
            painter.end()
            for i, (name, state) in enumerate(self.ROWS):
                row = QRect(0, 4 + i * 58, self.width(), 58)
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                card = QRectF(row).adjusted(RAIL_GUTTER, 2, -6, -2)
                painter.setPen(QPen(QColor(theme.BORDER), 1))
                painter.setBrush(QColor(theme.PANEL_2))
                painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), theme.RADIUS, theme.RADIUS)
                painter.setPen(QColor(theme.MUTED if state == RAIL_OFF else theme.TEXT))
                painter.drawText(card.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, name)
                paint_rail_node(painter, QRectF(row), state)
                painter.end()

    class Window(QMainWindow):
        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            paint_dots(painter, QRectF(event.rect()))
            painter.end()

    window = Window()
    body = QWidget()
    columns = QHBoxLayout(body)
    columns.setContentsMargins(12, 12, 12, 12)
    columns.setSpacing(8)
    panels = []
    for title in ("Inactive [2]", "Active [5]"):
        pane = QWidget()
        pane_layout = QVBoxLayout(pane)
        pane_layout.setContentsMargins(0, 0, 0, 0)
        label = TerminalLabel(title)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pane_layout.addWidget(label)
        panel = Rail() if title.startswith("Active") else QLabel()
        panel.setProperty("panel", True)
        panel.setMinimumSize(300, 320)
        pane_layout.addWidget(panel, 1)
        if isinstance(panel, QLabel):
            install_empty_grid(panel, lambda: True, over_default=True)
        panels.append(panel)
        columns.addWidget(pane)
    actions = QLabel()
    actions.setProperty("panel", True)
    actions.setFixedWidth(170)
    stack = QVBoxLayout(actions)
    for text, name, variant in (("Install", None, "accent-outline"), ("Installed", "check", None),
                                ("Updates", "warn", "warn-outline"), ("Modded", None, "primary")):
        button = QPushButton(text)
        if variant:
            button.setProperty("variant", variant)
        if name == "check":
            button.setProperty("installed", True)
            button.setEnabled(False)
            button.setIcon(icons.icon("check", theme.OK, theme.OK))
        elif name:
            button.setIcon(icons.icon(name, theme.WARN, theme.DISABLED_WARN))
        stack.addWidget(button)
    for kind in (QMessageBox.Icon.Question, QMessageBox.Icon.Warning, QMessageBox.Icon.Critical,
                 QMessageBox.Icon.Information):
        button = QPushButton(f"{kind.name} box")
        button.clicked.connect(lambda _=False, kind=kind: QMessageBox(kind, "VOLT", "A drawn dialog icon.",
                                                                      parent=window).exec())
        stack.addWidget(button)
    stack.addStretch(1)
    columns.addWidget(actions)
    panels.append(actions)
    install_shadows(body, panels)
    window.setCentralWidget(body)
    window.resize(900, 460)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    _preview()
